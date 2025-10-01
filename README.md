# immich_utils
Some scripts to manage data backups on Immich server

## Immich Asset Downloader

A Python script to download assets from an Immich server, excluding assets from external libraries.

### Features

- Fetches all assets from Immich server using pagination
- Filters out assets from external library (deviceId: "Library Import")
- Downloads assets with original filenames
- Handles assets with same file name
- Progress tracking and error handling
- Check asset integrity of downloaded assets using SHA1 (used by Immich)
- Uses Multi parallel process to speed up the integrity check
- Saves assets list to JSON file
- Deleter script moves the assets which pass integrity test to trash using pagination

### Installation

```bash
pip install -r requirements.txt
```

### Usage

#### Download all non-network drive assets:
```bash
python downloader.py https://your-immich-server.com YOUR_API_KEY
```

#### Specify output directory:
```bash
python downloader.py https://your-immich-server.com YOUR_API_KEY -o /path/to/output/folder
```

#### Only fetch and save assets list (don't download):
```bash
python downloader.py https://your-immich-server.com YOUR_API_KEY --list-only
```

#### Deleter script
```bash
python deleter.py https://your-immich-server.com YOUR_API_KEY
```

#### Deleter script from specific file
```bash
python deleter.py https://your-immich-server.com YOUR_API_KEY --deletion_file /path/to/file
```

### API Key

You need an API key with full access to your Immich server. You can generate one in your Immich admin panel under Settings > API Keys.

### Output

- Downloaded files are stored in `download/data/` folder
- Assets list is saved as `assets_to_download.json` in the `download/` folder
- Original filenames are preserved
