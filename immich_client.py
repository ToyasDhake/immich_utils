from pathlib import Path
import time
from typing import Any
import requests
import structlog
from tqdm import tqdm

logger = structlog.get_logger()

# POST /api/search/metadata accepts at most 1000 assets per page.
SEARCH_PAGE_SIZE = 1000

# Uploaded assets have no external library. Trashed assets are excluded, matching
# the old metadata search default.
UPLOADED_ASSET_FILTER: dict[str, Any] = {
    'libraryId': {'eq': None},
    'trashedAt': {'eq': None},
}

# External-library imports used to be marked with deviceId "Library Import".
# That field was removed in Immich v3; a non-null libraryId is the replacement.
EXTERNAL_LIBRARY_FILTER: dict[str, Any] = {
    'libraryId': {'ne': None},
    'trashedAt': {'eq': None},
}


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
    

    def get_current_user_id(self) -> str | None:
        """Return the id of the user who owns this API key."""
        try:
            response = requests.get(f'{self.server_url}/api/users/me', headers=self.headers)
            response.raise_for_status()
            user_id = response.json().get('id')
        except requests.exceptions.RequestException as e:
            self._log_request_error('Failed to fetch the current user', e)
            return None
        except ValueError as e:
            logger.error(f'Error decoding the current user: {e}')
            return None

        if not user_id:
            logger.error('Current user response did not include an id')
            return None
        return user_id


    def test_connection(self) -> bool:
        """Test connection to the Immich server."""
        try:
            response = requests.get(f'{self.server_url}/api/server/about', headers=self.headers)
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            self._log_request_error('Error connecting to Immich server', e)
            return False


    def _log_request_error(self, action: str, error: requests.exceptions.RequestException) -> None:
        detail = ''
        response = getattr(error, 'response', None)
        if response is not None and response.text:
            detail = response.text[:500]
        logger.error(f'{action}: {error} {detail}'.rstrip())


    def search_assets(self, asset_filter: dict[str, Any]) -> list[dict[str, Any]] | None:
        """Search assets with the Immich v3.2 metadata filter.

        Pages with the response cursor. The deprecated page/size fields cannot be
        combined with this filter and are removed in v4.
        """
        assets: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while True:
            payload: dict[str, Any] = {
                'size': SEARCH_PAGE_SIZE,
                'filter': asset_filter,
            }
            if cursor:
                payload['cursor'] = cursor

            try:
                response = requests.post(
                    f'{self.server_url}/api/search/metadata',
                    headers=self.headers,
                    json=payload,
                )
                response.raise_for_status()
                page = response.json().get('assets') or {}
            except requests.exceptions.RequestException as e:
                self._log_request_error('Error searching assets', e)
                return None
            except ValueError as e:
                logger.error(f'Error decoding asset search response: {e}')
                return None

            items = page.get('items') or []
            assets.extend(items)

            next_cursor = page.get('nextCursor')
            if not items or not next_cursor or next_cursor in seen_cursors:
                break

            seen_cursors.add(next_cursor)
            cursor = next_cursor
            logger.debug(f'Fetched {len(assets)} assets so far')

        return assets


    def fetch_album_assets(self, album_id: str) -> list[dict[str, Any]] | None:
        """Fetch every non-trashed asset in an album.

        Immich v3 removed the assets array from album responses. Album membership
        now comes from metadata search.
        """
        return self.search_assets({
            'albumIds': {'any': [album_id]},
            'trashedAt': {'eq': None},
        })


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
            self._log_request_error(f'Failed to download {original_filename}', e)
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
            self._log_request_error(f'Failed to delete {asset_ids}', e)
            return False


    def create_album(self, album_name: str, asset_ids: list[str] | None = None) -> str | None:
        """Create an album and return its id.

        Assets are optional. Large folders should be added afterwards in chunks.
        """
        if not album_name:
            album_name = 'Untitled'
        payload: dict[str, Any] = {'albumName': album_name}
        if asset_ids:
            payload['assetIds'] = asset_ids
        try:
            response = requests.post(
                f'{self.server_url}/api/albums',
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            album_id = response.json().get('id')
        except requests.exceptions.RequestException as e:
            self._log_request_error(f'Failed to create album {album_name}', e)
            return None
        except ValueError as e:
            logger.error(f'Error decoding created album {album_name}: {e}')
            return None

        if not album_id:
            logger.error(f'Create album response for {album_name} did not include an id')
            return None
        return album_id


    def add_assets_to_album(self, album_id: str, asset_ids: list[str]) -> list[str] | None:
        """Add assets to an album.

        Returns the ids Immich rejected. None means the request itself failed,
        so the caller does not know which ids were added.
        """
        if not asset_ids:
            return []
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
            results = response.json()
        except requests.exceptions.RequestException as e:
            self._log_request_error(f'Failed to add assets to album {album_id}', e)
            return None
        except ValueError as e:
            logger.error(f'Error decoding add-assets response for album {album_id}: {e}')
            return None

        failed: list[str] = []
        for item in results:
            if item.get('success', False):
                continue
            failed.append(item.get('id') or '')
            logger.error(
                f'Failed to add {item.get("id", "Unknown")} to album {album_id} '
                f'reason: {item.get("error", "Unknown")}'
            )
        return failed


    def fetch_albums(self) -> list[dict[str, Any]] | None:
        """Fetch all albums from the Immich server."""
        try:
            response = requests.get(
                f'{self.server_url}/api/albums',
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            self._log_request_error('Failed to fetch albums', e)
            return None
        except ValueError as e:
            logger.error(f'Error decoding album list: {e}')
            return None


    def fetch_album_info(self, album_id: str) -> dict[str, Any] | None:
        """Fetch a single album with its full asset list from the Immich server.

        Args:
            album_id: ID of the album to fetch
        """
        try:
            response = requests.get(
                f'{self.server_url}/api/albums/{album_id}',
                headers=self.headers
            )
            response.raise_for_status()
            album = response.json()
        except requests.exceptions.RequestException as e:
            self._log_request_error(f'Failed to fetch album {album_id}', e)
            return None
        except ValueError as e:
            logger.error(f'Error decoding album {album_id}: {e}')
            return None

        assets = self.fetch_album_assets(album_id)
        if assets is None:
            return None

        album['assets'] = assets
        return album


    def fetch_album_tree(self) -> tuple[dict[str, set[str]], dict[str, str]] | None:
        """Fetch album names, ids, and the asset ids currently in each album."""
        albums = self.fetch_albums()
        if albums is None:
            return None

        album_tree: dict[str, set[str]] = {}
        album_id_mapping: dict[str, str] = {}
        for album in albums:
            album_name = album['albumName']
            album_id = album['id']
            # Multiple albums can share a name. The last one returned is used,
            # which matches albums created from an asset's original path.
            if album_name in album_id_mapping:
                logger.warning(
                    f'Found multiple albums named "{album_name}", using the latest one'
                )
            assets = self.fetch_album_assets(album_id)
            if assets is None:
                return None
            album_tree[album_name] = {asset['id'] for asset in assets}
            album_id_mapping[album_name] = album_id
        return album_tree, album_id_mapping
