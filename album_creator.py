import argparse
import os
from pathlib import Path
from typing import Any
import structlog
from downloader import is_generated_file
from immich_client import EXTERNAL_LIBRARY_FILTER, ImmichClient

logger = structlog.get_logger()

# A failed request is retried one asset at a time, so keep each update bounded.
ALBUM_CHUNK_SIZE = 1000


class ImmichAbumCreator:
    def __init__(
        self, 
        server_url: str, 
        api_key: str, 
        path: str,
    ) -> None:
        """
        Initialize the Immich album creator.
        
        Args:
            server_url: Base URL of the Immich server (e.g., 'https://immich.example.com')
            api_key: API key with full access
            path: External library path
        """
        self.client = ImmichClient(server_url, api_key)
        self.path = path


    def fetch_all_assets(self, only_new: bool, user_id: str) -> list[dict[str, Any]] | None:
        """Fetch this user's external-library assets.

        Search also returns a partner's library when that partner is on the
        timeline. Those assets are dropped here. Generated motion clips are too.
        """
        logger.info('Fetching assets from Immich server...')

        asset_filter = dict(EXTERNAL_LIBRARY_FILTER)
        if only_new:
            asset_filter['hasAlbums'] = {'eq': False}

        assets = self.client.search_assets(asset_filter)
        if assets is None:
            logger.error('No data returned from Immich server')
            return None

        kept: list[dict[str, Any]] = []
        partner_count = 0
        generated_count = 0
        for asset in assets:
            if asset.get('ownerId') != user_id:
                partner_count += 1
                continue
            if is_generated_file(asset):
                generated_count += 1
                continue
            if not asset.get('libraryId'):
                continue
            kept.append(asset)

        if partner_count:
            logger.info(f'Skipping {partner_count} assets shared by a partner')
        if generated_count:
            logger.info(f'Skipping {generated_count} generated files under encoded-video')
        logger.info(f'Total assets: {len(kept)}')
        return kept


    def owned_albums(self, user_id: str) -> dict[str, str] | None:
        """Map album name to id for albums this user owns.

        Albums shared by a partner can reuse a folder name. Adding photos to
        one of those would fail or update the wrong album.
        """
        albums = self.client.fetch_albums()
        if albums is None:
            return None

        album_ids: dict[str, str] = {}
        for album in albums:
            owner_id = None
            for member in album.get('albumUsers') or []:
                if member.get('role') == 'owner':
                    owner_id = (member.get('user') or {}).get('id')
                    break
            if owner_id != user_id:
                continue

            album_name = album.get('albumName') or 'Untitled'
            if album_name in album_ids:
                logger.warning(
                    f'Found multiple albums named "{album_name}", using the latest one'
                )
            album_ids[album_name] = album['id']
        return album_ids


    def add_assets(self, album_id: str, asset_ids: list[str]) -> bool:
        """Add assets in chunks. Retry one by one only when the whole request fails."""
        added = True
        for offset in range(0, len(asset_ids), ALBUM_CHUNK_SIZE):
            chunk = asset_ids[offset:offset + ALBUM_CHUNK_SIZE]
            failed = self.client.add_assets_to_album(album_id, chunk)
            if failed is None:
                logger.warning(f'Chunk of {len(chunk)} failed for album {album_id}, retrying each asset')
                for asset_id in chunk:
                    retry = self.client.add_assets_to_album(album_id, [asset_id])
                    if retry is None or retry:
                        added = False
                continue
            if failed:
                added = False
        return added


    def run(self, only_new: bool = True) -> None:
        """
        Run the Immich album creator.
        """
        logger.info('Creating albums...')

        user_id = self.client.get_current_user_id()
        if user_id is None:
            logger.error('Cannot create albums without the current user id')
            return

        assets = self.fetch_all_assets(only_new, user_id)
        if assets is None:
            return

        album_id_mapping = self.owned_albums(user_id)
        if album_id_mapping is None:
            return

        album_tree: dict[str, set[str]] = {name: set() for name in album_id_mapping}
        if not only_new:
            for album_name, album_id in album_id_mapping.items():
                album_assets = self.client.fetch_album_assets(album_id)
                if album_assets is None:
                    return
                album_tree[album_name] = {asset['id'] for asset in album_assets}

        if not assets:
            logger.info('No assets found to create album')
            return

        if only_new:
            logger.info(f'Found {len(assets)} new assets')

        existing_album_new_assets: dict[str, list[str]] = {}
        new_album_assets: dict[str, list[str]] = {}
        prefix_to_remove = Path(self.path)
        outside_count = 0
        outside_example: Path | None = None

        for asset in assets:
            raw_path = asset.get('originalPath')
            if not raw_path:
                outside_count += 1
                continue
            original_path = Path(raw_path)
            if not original_path.is_relative_to(prefix_to_remove):
                outside_count += 1
                outside_example = outside_example or original_path
                continue
            relative_path = str(original_path.relative_to(prefix_to_remove))
            album_name = os.path.split(relative_path)[0].replace('/', ' ') or 'Untitled'
            if album_name in album_tree:
                if asset['id'] not in album_tree[album_name]:
                    existing_album_new_assets.setdefault(album_id_mapping[album_name], []).append(asset['id'])
            else:
                new_album_assets.setdefault(album_name, []).append(asset['id'])

        if outside_count:
            logger.info(f'Skipping {outside_count} assets outside {prefix_to_remove}')
        if outside_example and not existing_album_new_assets and not new_album_assets:
            logger.error(
                f'No assets were under {prefix_to_remove}. '
                f'Pass the path Immich stores. Example: {outside_example}'
            )
            return

        for album_name, album_assets in new_album_assets.items():
            logger.info(f'Creating album {album_name} with {len(album_assets)} assets')
            album_id = self.client.create_album(album_name)
            if not album_id:
                logger.error(f'Failed to create album {album_name}')
                continue
            if not self.add_assets(album_id, album_assets):
                logger.error(f'Album {album_name} was created, but some assets were not added')
                continue
            logger.info(f'Album {album_name} created successfully')

        for album_id, album_assets in existing_album_new_assets.items():
            logger.info(f'Adding {len(album_assets)} assets to existing album {album_id}')
            if not self.add_assets(album_id, album_assets):
                logger.error(f'Some assets were not added to album {album_id}')
                continue
            logger.info(f'Assets added to existing album {album_id} successfully')


def main(args: argparse.Namespace) -> None:
    creator = ImmichAbumCreator(args.server_url, args.api_key, args.path)
    creator.run()
    

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create albums for external library')
    parser.add_argument('server_url', help='Immich server URL (e.g., https://immich.example.com)')
    parser.add_argument('api_key', help='API key with full access')
    parser.add_argument('path', help='Extrnal libray path')

    
    args = parser.parse_args()

    main(args)
