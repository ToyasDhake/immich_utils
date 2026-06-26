import argparse
from pathlib import Path
from typing import Any
import structlog
from downloader import ImmichDownloader

logger = structlog.get_logger()


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

        matches = [album for album in albums if album.get('albumName') == self.album_name]

        if not matches:
            logger.error(f'No album found with name "{self.album_name}"')
            available = ', '.join(sorted(album.get('albumName', '') for album in albums))
            logger.info(f'Available albums: {available}')
            return None

        if len(matches) > 1:
            logger.warning(
                f'Found {len(matches)} albums named "{self.album_name}", using the first one'
            )

        return matches[0]['id']


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

        assets = album.get('assets', [])
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
        self.save_assets_list(assets, filename=f'{self.album_name}_assets.json')

        logger.info('Completed without any errors')


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
