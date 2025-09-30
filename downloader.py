#!/usr/bin/env python3
"""
Immich Asset Downloader

This script fetches images and videos from an Immich server that are not from
the network drive (deviceId != "Library Import") and downloads them locally.
"""

import requests
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any
import argparse
from urllib.parse import urljoin


class ImmichDownloader:
    def __init__(self, server_url: str, api_key: str, output_dir: str = "downloads"):
        """
        Initialize the Immich downloader.
        
        Args:
            server_url: Base URL of the Immich server (e.g., "https://immich.example.com")
            api_key: API key with full access
            output_dir: Directory to save downloaded files
        """
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        self.output_dir = Path(output_dir)
        self.data_dir = self.output_dir / "data"
        self.output_dir.mkdir(exist_ok=True)
        self.data_dir.mkdir(exist_ok=True)
        
        self.headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json"
        }
        
        # Store assets to download
        self.assets_to_download: List[Dict[str, Any]] = []
        
    def test_connection(self) -> bool:
        """Test connection to the Immich server."""
        try:
            response = requests.get(f"{self.server_url}/api/server/about", headers=self.headers)
            response.raise_for_status()
            print(f"✓ Connected to Immich server: {self.server_url}")
            return True
        except requests.exceptions.RequestException as e:
            print(f"✗ Failed to connect to Immich server: {e}")
            return False
    
    def fetch_all_assets(self) -> List[Dict[str, Any]]:
        """
        Fetch all assets from the Immich server using pagination.
        Filters out assets with deviceId "Library Import".
        """
        print("Fetching assets from Immich server...")
        
        all_assets = []
        page = 1
        size = 100  # Fetch 100 assets per page for efficiency
        
        while True:
            print(f"Fetching page {page}...")
            
            payload = {
                "size": size,
                "page": page
            }
            
            try:
                response = requests.post(
                    f"{self.server_url}/api/search/metadata",
                    headers=self.headers,
                    json=payload
                )
                response.raise_for_status()
                
                data = response.json()
                assets = data.get("assets", {}).get("items", [])
                
                if not assets:
                    break
                
                # Filter out assets from network drive
                filtered_assets = [
                    asset for asset in assets 
                    if asset.get("deviceId") != "Library Import"
                ]
                
                all_assets.extend(filtered_assets)
                print(f"  Found {len(assets)} assets, {len(filtered_assets)} not from network drive")
                
                # Check if there's a next page
                if not data.get("assets", {}).get("nextPage"):
                    break
                    
                page += 1
                
            except requests.exceptions.RequestException as e:
                print(f"✗ Error fetching page {page}: {e}")
                break
        
        print(f"✓ Total assets to download: {len(all_assets)}")
        return all_assets
    
    def save_assets_list(self, assets: List[Dict[str, Any]], filename: str = "assets_to_download.json"):
        """Save the list of assets to download to a JSON file."""
        filepath = self.output_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(assets, f, indent=2, ensure_ascii=False)
        
        print(f"✓ Assets list saved to: {filepath}")
    
    def download_asset(self, asset: Dict[str, Any]) -> bool:
        """
        Download a single asset from the Immich server.
        
        Args:
            asset: Asset metadata from the API
            
        Returns:
            bool: True if download successful, False otherwise
        """
        asset_id = asset["id"]
        original_filename = asset["originalFileName"]
        
        # Save all files in the data directory
        filepath = self.data_dir / original_filename
        
        # Skip if file already exists
        if filepath.exists():
            print(f"  ⏭️  Skipping {original_filename} (already exists)")
            return True
        
        try:
            # Download the asset
            response = requests.get(
                f"{self.server_url}/api/assets/{asset_id}",
                headers=self.headers,
                stream=True
            )
            response.raise_for_status()
            
            # Save the file
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            print(f"  ✓ Downloaded: {original_filename}")
            return True
            
        except requests.exceptions.RequestException as e:
            print(f"  ✗ Failed to download {original_filename}: {e}")
            return False
    
    def download_all_assets(self, assets: List[Dict[str, Any]]):
        """Download all assets in the list."""
        if not assets:
            print("No assets to download.")
            return
        
        print(f"\nStarting download of {len(assets)} assets...")
        
        successful_downloads = 0
        failed_downloads = 0
        
        for i, asset in enumerate(assets, 1):
            print(f"[{i}/{len(assets)}] {asset['originalFileName']}")
            
            if self.download_asset(asset):
                successful_downloads += 1
            else:
                failed_downloads += 1
        
        print(f"\n✓ Download complete!")
        print(f"  Successful: {successful_downloads}")
        print(f"  Failed: {failed_downloads}")
    
    def run(self, download: bool = True):
        """
        Main method to run the downloader.
        
        Args:
            download: If True, download the assets. If False, only fetch and save the list.
        """
        print("Immich Asset Downloader")
        print("=" * 50)
        
        # Test connection
        if not self.test_connection():
            return False
        
        # Fetch all assets
        assets = self.fetch_all_assets()
        
        if not assets:
            print("No assets found to download.")
            return True
        
        # Save assets list to JSON
        self.save_assets_list(assets)
        
        # Download assets if requested
        if download:
            self.download_all_assets(assets)
        
        return True


def main():
    parser = argparse.ArgumentParser(description="Download assets from Immich server")
    parser.add_argument("server_url", help="Immich server URL (e.g., https://immich.example.com)")
    parser.add_argument("api_key", help="API key with full access")
    parser.add_argument("-o", "--output", default="downloads", help="Output directory (default: downloads)")
    parser.add_argument("--list-only", action="store_true", help="Only fetch and save the assets list, don't download")
    
    args = parser.parse_args()
    
    downloader = ImmichDownloader(args.server_url, args.api_key, args.output)
    success = downloader.run(download=not args.list_only)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
