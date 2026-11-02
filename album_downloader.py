import argparse
from typing import Any
import structlog
from downloader import ImmichDownloader, is_generated_file

logger = structlog.get_logger()


def album_owner_id(album: dict[str, Any]) -> str | None:
    """Return the owning user's id. Immich puts that member on albumUsers."""
    for member in album.get('albumUsers') or []:
        if member.get('role') == 'owner':
            return (member.get('user') or {}).get('id')
    return None


def json_filename(album_name: str) -> str:
    """Keep the assets list inside the output directory."""
    safe_name = album_name.replace('/', ' ').replace('\\', ' ').strip() or 'album'
    return f'{safe_name}_assets.json'


class ImmichAlbumDownloader(ImmichDownloader):
    def __init__(
        self,
        server_url: str,
        api_key: str,
        album_name: str,
        output_dir: str = 'downloads',
    ) -> None:
        """
        Initialize the Immich album downloader.

        Args:
            server_url: Base URL of the Immich server (e.g., 'https://immich.example.com')
            api_key: API key with full access
            album_name: Name of the album to download
            output_dir: Directory to save downloaded files
        """
        self.album_name = album_name
        super().__init__(server_url, api_key, output_dir)


    def resolve_album_id(self) -> str | None:
        """Resolve the album name to an album ID.

        Returns:
            The album ID, or None if no matching album is found.
        """
        albums = self.client.fetch_albums()
        if albums is None:
            logger.error('Failed to fetch albums')
            return None

        matches = [album for album in albums if album.get('albumName') == self.album_name]

        if not matches:
            logger.error(f'No album found with name "{self.album_name}"')
            available = ', '.join(sorted(album.get('albumName', '') for album in albums))
            logger.info(f'Available albums: {available}')
            return None

        if len(matches) == 1:
            return matches[0]['id']

        user_id = self.client.get_current_user_id()
        if user_id is None:
            logger.error(
                f'Found {len(matches)} albums named "{self.album_name}", '
                'and the current user could not be resolved'
            )
            return None

        owned = [album for album in matches if album_owner_id(album) == user_id]
        if owned:
            if len(owned) > 1:
                logger.warning(
                    f'Found {len(owned)} albums you own named "{self.album_name}", using the latest one'
                )
            else:
                logger.info(
                    f'Found {len(matches)} albums named "{self.album_name}", using the one you own'
                )
            return owned[-1]['id']

        logger.warning(
            f'Found {len(matches)} shared albums named "{self.album_name}", '
            'none owned by you, using the latest one'
        )
        return matches[-1]['id']


    def fetch_album_assets(self) -> list[dict[str, Any]]:
        """
        Fetch all assets belonging to the configured album.
        """
        logger.info(f'Fetching assets for album "{self.album_name}"...')

        album_id = self.resolve_album_id()
        if album_id is None:
            return []

        album = self.client.fetch_album_info(album_id)
        if not album:
            logger.error(f'Failed to fetch album "{self.album_name}"')
            return []

        assets = [
            asset for asset in album.get('assets', [])
            if asset.get('id') and asset.get('originalFileName') and not is_generated_file(asset)
        ]
        generated_count = sum(1 for asset in album.get('assets', []) if is_generated_file(asset))
        if generated_count:
            logger.info(f'Skipping {generated_count} generated files under encoded-video')

        user_id = self.client.get_current_user_id()
        if user_id is not None:
            shared_count = sum(1 for asset in assets if asset.get('ownerId') != user_id)
            if shared_count:
                logger.info(
                    f'{shared_count} assets in this album belong to someone else. '
                    'They will download. The deleter will not trash them.'
                )

        logger.info(f'Total assets to download: {len(assets)}')
        return assets


    def run(self, download: bool = True) -> None:
        """
        Main method to download all assets in the album and check their integrity.

        Args:
            download: If True, download the assets. If False, only fetch and save the list.
        """
        logger.info('Running Immich album downloader')

        # Test connection
        if not self.client.test_connection():
            logger.error('Unable to connect to Immich server')
            return

        # Fetch all assets in the album
        assets = self.fetch_album_assets()

        if not assets:
            logger.info('No assets found to download')
            return

        # Download assets if requested
        if download:
            self.download_all_assets(assets)

            # Check integrity of the downloaded assets
            assets = self.check_downloaded_assets_integrity(assets)

        # Save assets list to JSON
        self.save_assets_list(assets, filename=json_filename(self.album_name))
        self.report_result(assets, downloaded=download)


def main(args: argparse.Namespace) -> None:
    downloader = ImmichAlbumDownloader(
        args.server_url, args.api_key, args.album_name, args.output
    )
    downloader.run(download=not args.list_only)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Download all assets in an Immich album')
    parser.add_argument('server_url', help='Immich server URL (e.g., https://immich.example.com)')
    parser.add_argument('api_key', help='API key with full access')
    parser.add_argument('album_name', help='Name of the album to download')
    parser.add_argument('-o', '--output', default='downloads', help='Output directory (default: downloads)')
    parser.add_argument('--list-only', action='store_true',
            help='Only fetch and save the assets list, do not download')

    args = parser.parse_args()

    main(args)
