import argparse
import os
from pathlib import Path
from typing import Any
import structlog
from immich_client import ImmichClient

DEVICE_ID = 'Library Import'

logger = structlog.get_logger()


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


    def fetch_all_assets(self) -> list[dict[str, Any]]:
        """
        Fetch all assets from the Immich server using pagination.
        Filter assets with deviceId 'Library Import'.
        """
        logger.info('Fetching assets from Immich server...')
        
        all_assets = []
        page = 1
        size = 100  # Fetch 100 assets per page for efficiency

        while True:
            logger.debug(f'Fetching page {page}...')
            
            payload = {
                'size': size,
                'page': page
            }
            
            data = self.client.fetch_assets_info(payload)

            if not data:
                logger.error('No data returned from Immich server')
                break
                
            assets = data.get('assets', {}).get('items', [])
            
            if not assets:
                logger.error('No assets returned from Immich server')
                break
            
            # Filter assets for external library
            filtered_assets = [
                asset for asset in assets 
                if asset.get('deviceId') == DEVICE_ID
            ]

            all_assets.extend(filtered_assets)
            logger.debug(f'Found {len(all_assets)} assets so far')
            
            # Check if there's a next page
            if not data.get('assets', {}).get('nextPage'):
                logger.info('All pages fetched')
                break
            page += 1
            
        logger.info(f'Total assets: {len(all_assets)}')
        return all_assets


    def run(self, only_new: bool = True) -> None:
        """
        Run the Immich album creator.
        """
        logger.info(f'Creating albums...')

        assets = self.fetch_all_assets()

        album_tree, album_id_mapping = self.client.fetch_album_tree()
        
        if not assets:
            logger.info('No assets found to create album')
            return

        existing_album_new_assets = {}
        new_album_assets = {}
        prefix_to_remove = Path(self.path)

        if only_new:
            all_assets_in_albums = set().union(*album_tree.values())
            assets = [asset for asset in assets if asset['id'] not in all_assets_in_albums]
            logger.info(f'Found {len(assets)} new assets')

        for asset in assets:
            asset['originalPath'] = str(Path(asset['originalPath']).relative_to(prefix_to_remove))
            album_name = os.path.split(asset['originalPath'])[0].replace('/', ' ')
            if album_name in album_tree:
                if asset['id'] not in album_tree[album_name]:
                    if album_id_mapping[album_name] not in existing_album_new_assets:
                        existing_album_new_assets[album_id_mapping[album_name]] = []
                    existing_album_new_assets[album_id_mapping[album_name]].append(asset['id'])
            else:
                if album_name not in new_album_assets:
                    new_album_assets[album_name] = []
                new_album_assets[album_name].append(asset['id'])

        for album_name, album_assets in new_album_assets.items():
            logger.info(f'Creating album {album_name} with {len(album_assets)} assets')
            result = self.client.create_album(album_name, album_assets)
            if not result:
                logger.error(f'Failed to create album {album_name}')
                continue
            logger.info(f'Album {album_name} created successfully')

        for album_id, album_assets in existing_album_new_assets.items():
            logger.info(f'Adding assets to existing album {album_id} with {len(album_assets)} assets')
            result = self.client.add_assets_to_album(album_id, album_assets)
            if not result:
                logger.error(f'Failed to add assets to existing album {album_id}')
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
