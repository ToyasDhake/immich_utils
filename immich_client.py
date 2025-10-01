from pathlib import Path
import time
from typing import Any
import requests
import structlog
from tqdm import tqdm

logger = structlog.get_logger()


class ImmichClient:
    def __init__(self, server_url: str, api_key: str) -> None:
        """
        Initialize the Immich Client.
        
        Args:
            server_url: Base URL of the Immich server (e.g., 'https://immich.example.com')
            api_key: API key with full access
        """
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        
        self.headers = {
            'x-api-key': api_key,
            'Content-Type': 'application/json'
        }
    

    def test_connection(self) -> bool:
        """Test connection to the Immich server."""
        try:
            response = requests.get(f'{self.server_url}/api/server/about', headers=self.headers)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            return False

    
    def fetch_assets_info(self, payload: dict[str, int]) -> list[dict[str, Any]] | None:
        """Fetch assets information from the Immich server."""
        try:
            response = requests.post(
                f'{self.server_url}/api/search/metadata',
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f'Error fetching page {payload["page"]}: {e}')
            return None


    def download_asset(
        self, 
        asset_id: str, 
        filepath: Path, 
        original_filename: str,
    ) -> str:
        try:
            # Download the asset file content
            response = requests.get(
                f'{self.server_url}/api/assets/{asset_id}/original',
                headers=self.headers,
                stream=True
            )
            response.raise_for_status()
            
            # Get total file size for progress tracking
            total_size = int(response.headers.get('content-length', 0))
            
            # Save the file with progress tracking
            with open(filepath, 'wb') as f:
                downloaded = 0
                start_time = time.time()
                
                # Create progress bar
                with tqdm(
                    total=total_size,
                    unit='B',
                    unit_scale=True,
                    unit_divisor=1024,
                    desc=f'{original_filename[:30]}{"..." if len(original_filename) > 30 else ""}',
                    ncols=100,
                    leave=False
                ) as pbar:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            # Update progress bar
                            pbar.update(len(chunk))
                            
                            # Calculate and display speed
                            elapsed_time = time.time() - start_time
                            if elapsed_time > 0:
                                speed_mbps = (downloaded / (1024 * 1024)) / elapsed_time
                                pbar.set_postfix(speed=f'{speed_mbps:.2f} MB/s')
            
            downloaded_mb = downloaded / (1024 * 1024)
            logger.info(f'Downloaded: {original_filename} ({downloaded_mb:.2f} MB)')
            return filepath.name
            
        except requests.exceptions.RequestException as e:
            logger.error(f'Failed to download {original_filename}: {e}')
            return ''
            