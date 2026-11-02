import argparse
import base64
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
from typing import Any
import structlog
from immich_client import UPLOADED_ASSET_FILTER, ImmichClient

logger = structlog.get_logger()


def is_generated_file(asset: dict[str, Any]) -> bool:
    """True for files Immich created, such as an extracted Android motion clip.

    Those live under the encoded-video folder. The JPEG they came from is the
    original and is downloaded on its own. A transcode of a normal video is not
    a separate asset, so this does not drop real uploaded videos.
    """
    original_path = (asset.get('originalPath') or '').replace('\\', '/')
    return '/encoded-video/' in original_path


class ImmichDownloader:
    def __init__(
        self, 
        server_url: str, 
        api_key: str, 
        output_dir: str = 'downloads',
    ) -> None:
        """
        Initialize the Immich downloader.
        
        Args:
            server_url: Base URL of the Immich server (e.g., 'https://immich.example.com')
            api_key: API key with full access
            output_dir: Directory to save downloaded files
        """
        self.client = ImmichClient(server_url, api_key)

        self.output_dir = Path(output_dir)
        self.data_dir = self.output_dir / 'data'
        self.output_dir.mkdir(exist_ok=True)
        self.data_dir.mkdir(exist_ok=True)


    def fetch_all_assets(self) -> list[dict[str, Any]]:
        """
        Fetch uploaded assets from the Immich server.

        External-library assets are left on the server. Trashed assets are skipped.
        Partner-shared assets are skipped. Search includes them whenever a partner
        is shown on your timeline, and there is no search filter for owner.
        """
        logger.info('Fetching assets from Immich server...')

        user_id = self.client.get_current_user_id()
        if user_id is None:
            return []

        assets = self.client.search_assets(UPLOADED_ASSET_FILTER)
        if assets is None:
            logger.error('No data returned from Immich server')
            return []

        partner_count = sum(1 for asset in assets if asset.get('ownerId') != user_id)
        assets = [asset for asset in assets if asset.get('ownerId') == user_id]
        if partner_count:
            logger.info(f'Skipping {partner_count} assets shared by a partner')

        generated_count = sum(1 for asset in assets if is_generated_file(asset))
        assets = [asset for asset in assets if not is_generated_file(asset)]
        if generated_count:
            logger.info(f'Skipping {generated_count} generated files under encoded-video')

        logger.info(f'Total assets to download: {len(assets)}')
        return assets


    def get_unique_filepath(self, directory: Path, filename: str) -> Path | None:
        """
        Generate a unique filepath by adding _1, _2, etc. suffix if file exists.
        
        Args:
            directory: Directory where the file should be saved
            filename: Original filename
            
        Returns:
            Path: Unique filepath, or None if unable to find unique name
        """
        filepath = directory / filename
        
        # If file doesn't exist, return the original path
        if not filepath.exists():
            return filepath
        
        # Split filename and extension
        name, ext = os.path.splitext(filename)
        
        # Try adding _1, _2, etc. until we find a unique name
        counter = 1
        while counter < 1000:  # Prevent infinite loop
            new_filename = f"{name}_{counter}{ext}"
            new_filepath = directory / new_filename
            
            if not new_filepath.exists():
                logger.info(f'Renaming {filename} to {new_filename} (duplicate found)')
                return new_filepath
            
            counter += 1
        
        # If we couldn't find a unique name after 1000 attempts, return None
        return None


    def download_asset(self, asset: dict[str, Any]) -> str:
        """
        Download a single asset from the Immich server.
        
        Args:
            asset: Asset metadata from the API
            
        Returns:
            bool: True if download successful, False otherwise
        """
        asset_id = asset['id']
        original_filename = asset['originalFileName']
        
        # Generate unique filename if file already exists
        filepath = self.get_unique_filepath(self.data_dir, original_filename)
        
        # Skip if file already exists and we couldn't find a unique name
        if filepath is None:
            logger.error(f'Skipping {original_filename} (unable to find unique filename)')
            return ''

        return self.client.download_asset(asset_id, filepath, original_filename)


    def download_all_assets(
        self, 
        assets: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        """Download all assets in the list."""
        if not assets:
            logger.error('No assets to download')
            return
         
        logger.info(f'Starting download of {len(assets)} assets')
        
        successful_downloads = 0
        failed_downloads = 0
        
        for i, asset in enumerate(assets, 1):
            logger.info(f'[{i}/{len(assets)}] {asset["originalFileName"]}')
            
            download_filename = self.download_asset(asset)
            if download_filename != '':
                asset['downloadFileName'] = download_filename
                successful_downloads += 1
            else:
                failed_downloads += 1
        
        logger.info(f'Download complete!')
        logger.info(f'Successful: {successful_downloads}')
        if failed_downloads > 0:
            logger.error(f'Failed: {failed_downloads}')
        return assets


    def run_hash_check(self, asset: dict[str, Any]) -> str:
        
        if 'downloadFileName' not in asset:
            logger.error(f'Download did not complete for {asset["originalFileName"]}')
            return 'missing'
        
        file_path = self.data_dir / asset['downloadFileName']
        
        # Check if file exists
        if not os.path.exists(file_path):
            logger.error(f'{asset["downloadFileName"]} not found')
            return 'missing'
        
        # Check SHA1 checksum if available
        if 'checksum' in asset and asset['checksum']:
            try:
                # Calculate SHA1 of the downloaded file
                sha1_hash = hashlib.sha1()
                with open(file_path, 'rb') as f:
                    for chunk in iter(lambda: f.read(8192), b''):
                        sha1_hash.update(chunk)
                
                # Get the calculated hash as base64
                calculated_checksum = base64.b64encode(sha1_hash.digest()).decode('utf-8')
                
                # Compare with stored checksum
                if calculated_checksum != asset['checksum']:
                    logger.error(f'{asset["downloadFileName"]} checksum mismatch')
                    return 'mismatch'
                else:
                    return 'verified'
                    
            except Exception as e:
                logger.error(f'{asset["downloadFileName"]} checksum verification failed: {e}')
                return 'mismatch'
        else:
            return 'no_checksum'

    
    def check_downloaded_assets_integrity(
        self, 
        assets: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]] | None:
        """Check the integrity of the downloaded assets."""
        if not assets:
            logger.error('No assets to check integrity of')
            return

        logger.info('Checking downloaded assets integrity...')

        # Leave at least one core free, and never ask for zero workers.
        workers = max(1, (os.cpu_count() or 1) - 2)
        with multiprocessing.Pool(processes=workers) as pool:
            results = pool.map(self.run_hash_check, assets)

        for result, asset in zip(results, assets):
            if result in ['missing', 'mismatch']:
                logger.info(f'Retrying download for {asset["originalFileName"]}')
                download_filename = self.download_asset(asset)
                if download_filename != '':
                    asset['downloadFileName'] = download_filename
                    result = self.run_hash_check(asset)
                    if result in ['missing', 'mismatch']:
                        logger.error(f'Failed to download {asset["originalFileName"]}')
                        result += '_failed'
                else:
                    logger.error(f'Failed to download {asset["originalFileName"]}')
                    result = 'failed_redownload'
                    
            asset['integrity'] = result

        verified = sum(1 for asset in assets if asset.get('integrity') == 'verified')
        logger.info(f'Integrity check complete: {verified} of {len(assets)} verified')
        counts: dict[str, int] = {}
        for asset in assets:
            status = asset.get('integrity') or 'unknown'
            if status != 'verified':
                counts[status] = counts.get(status, 0) + 1
        for status, count in sorted(counts.items()):
            logger.warning(f'{status}: {count}')

        return assets


    def save_assets_list(
        self, 
        assets: list[dict[str, Any]] | None, 
        filename: str = 'downloaded_assets.json',
    ) -> None:
        """Save the list of assets to download to a JSON file."""
        if not assets:
            logger.error('No assets to save')
            return

        filepath = self.output_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(assets, f, indent=4, ensure_ascii=False)
        
        logger.info(f'Assets list saved to: {filepath}')


    def run(self, download: bool = True) -> None:
        """
        Main method to run the downloader and check itegrity of the downloaded assets.
        
        Args:
            download: If True, download the assets. If False, only fetch and save the list.
        """
        logger.info('Running Immich downloader')

        # Test connection
        if not self.client.test_connection():
            logger.error('Unable to connect to Immich server')
            return

        # Fetch all assets
        assets = self.fetch_all_assets()

        if not assets:
            logger.info('No assets found to download')
            return

        # Download assets if requested
        if download:
            self.download_all_assets(assets)

            # Check integrity of the downloaded assets
            assets = self.check_downloaded_assets_integrity(assets)

        # Save assets list to JSON
        self.save_assets_list(assets)
        self.report_result(assets, downloaded=download)


    def report_result(self, assets: list[dict[str, Any]], downloaded: bool) -> None:
        """Say whether the saved list is safe to pass to the deleter."""
        if not downloaded:
            logger.info('List saved. Checksums were not checked, so the deleter will not trash these assets.')
            return

        verified = sum(1 for asset in assets if asset.get('integrity') == 'verified')
        logger.info(f'{verified} of {len(assets)} assets are verified and can be trashed')
        if verified != len(assets):
            logger.error(f'{len(assets) - verified} assets were not verified and will stay on the server')


def main(args: argparse.Namespace) -> None:
    downloader = ImmichDownloader(args.server_url, args.api_key, args.output)
    downloader.run(download=not args.list_only)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Download assets from Immich server')
    parser.add_argument('server_url', help='Immich server URL (e.g., https://immich.example.com)')
    parser.add_argument('api_key', help='API key with full access')
    parser.add_argument('-o', '--output', default='downloads', help='Output directory (default: downloads)')
    parser.add_argument('--list-only', action='store_true', 
            help='Only fetch and save the assets list, do not download')
    
    args = parser.parse_args()

    main(args)
