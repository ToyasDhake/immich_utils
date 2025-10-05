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


    def delete_assets(self, asset_ids: list[str], force: bool = False) -> bool:
        """Delete assets from the Immich server.
        
        Args:
            asset_ids: List of asset IDs to delete
            force: Whether to force deletion (default: False)
        """
        try:
            payload = {
                'force': force,
                'ids': asset_ids
            }
            response = requests.delete(
                f'{self.server_url}/api/assets',
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f'Failed to delete {asset_ids}: {e}')
            return False


    def create_album(self, album_name: str, asset_ids: list[str]) -> bool:
        """Create an album on the Immich server.
        
        Args:
            album_name: Name of the album
            asset_ids: List of asset IDs to add to the album
        """
        if not album_name:
            album_name = 'Untitled'
        try:
            payload = {
                'albumName': album_name,
                'assetIds': asset_ids
            }
            response = requests.post(
                f'{self.server_url}/api/albums',
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f'Failed to create album {album_name}: {e}')
            return False


    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> bool:
        """Add assets to an existing album on the Immich server."""
        try:
            payload = {
                'ids': asset_ids
            }
            response = requests.put(
                f'{self.server_url}/api/albums/{album_id}/assets',
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            for resp in response.json():
                if not resp.get('success', False):
                    logger.error(f'Failed to add {resp.get("id", "Unknown")} to album {album_id} reason: {resp.get("error", "Unknown")}')
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f'Failed to add assets to album {album_id}: {e}')
            return False


    def fetch_albums(self) -> list[str]:
        """Fetch all albums from the Immich server."""
        try:
            response = requests.get(
                f'{self.server_url}/api/albums',
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f'Failed to fetch albums: {e}')
            return []


    def fetch_album_tree(self) -> tuple[dict[str, list[str]], dict[str, str]]:
        """Fetch album tree from the Immich server."""
        try:
            album_ids = [album['id'] for album in self.fetch_albums()]
            album_tree = {}
            album_id_mapping = {}
            for album_id in album_ids:
                response = requests.get(
                    f'{self.server_url}/api/albums/{album_id}',
                    headers=self.headers
                )
                response.raise_for_status()
                album = response.json()
                album_tree[album['albumName']] = set([asset['id'] for asset in album['assets']])
                # This is not a one to one mapping, there can be multiple albums with the same name
                # But ideally because we are creating albums bases on the path of the assets,
                # there should be only one album with the same name
                # If there are multiple albums with the same name, which is seen last will be the one used
                album_id_mapping[album['albumName']] = album['id']
            return album_tree, album_id_mapping
        except requests.exceptions.RequestException as e:
            logger.error(f'Failed to fetch albums: {e}')
            return {}, {}
