import argparse
import base64
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
from typing import Any
import structlog
from immich_client import ImmichClient

logger = structlog.get_logger()

DEVICE_ID_TO_SKIP = 'Library Import'


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
        Fetch all assets from the Immich server using pagination.
        Filters out assets with deviceId 'Library Import'.
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
            
            # Filter out assets from network drive
            filtered_assets = [
                asset for asset in assets 
                if asset.get('deviceId') != DEVICE_ID_TO_SKIP
            ]
            
            all_assets.extend(filtered_assets)
            logger.debug(f'Found {len(all_assets)} assets so far')
            
            # Check if there's a next page
            if not data.get('assets', {}).get('nextPage'):
                logger.info('All pages fetched')
                break
            page += 1
            
        logger.info(f'Total assets to download: {len(all_assets)}')
        return all_assets


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

        with multiprocessing.Pool(processes=multiprocessing.cpu_count()-2) as pool:
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

        # Summary
        logger.info('Integrity check complete:')
        if results.count('missing') > 0:
            logger.warning(f'Missing files: {results.count("missing")}')
        if results.count('mismatch') > 0:
            logger.warning(f'Checksum mismatches: {results.count("mismatch")}')
        logger.info(f'Total checked: {len(assets)}')

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
        
        logger.info('Completed without any errors')


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
