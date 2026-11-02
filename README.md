# immich_utils
Some scripts to manage data backups on Immich server

These scripts target Immich 3.2 and newer. The current stable server release is v3.3.5, and the same API calls are what v3.4.0-rc.1 documents. They will not run against Immich v2: v3 removed `deviceId` and the asset list on albums, and v3.2 replaced paged metadata search with a filter and cursor.

## Immich Asset Downloader

A Python script to download assets from an Immich server, excluding assets from external libraries.

### Features

- Fetches uploaded assets with the metadata search filter (`libraryId` is null)
- Skips external-library assets and assets in the trash
- Includes archived and hidden assets, which current search returns alongside timeline assets
- Skips generated files under encoded-video, including motion clips Immich extracted from a JPEG. The original file is downloaded instead
- Skips photos and videos shared by a partner. Search includes those whenever the partner is shown on your timeline
- Downloads assets with original filenames
- Handles assets with same file name
- Progress tracking and error handling
- Check asset integrity of downloaded assets using SHA1 (used by Immich)
- Uses Multi parallel process to speed up the integrity check
- Saves assets list to JSON file
- Deleter script moves verified assets you own to the trash. Partner assets, external-library files, and generated encoded-video files are skipped

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

#### Download all assets (images and videos) in a specific album:

If several albums share that name, the one you own is used. Photos someone else added to the album are downloaded with it. Generated encoded-video files are skipped. The deleter will not trash the other person's photos.
```bash
python album_downloader.py https://your-immich-server.com YOUR_API_KEY "Album Name"
```

#### Download an album to a specific output directory:
```bash
python album_downloader.py https://your-immich-server.com YOUR_API_KEY "Album Name" -o /path/to/output/folder
```

#### Only fetch and save the album's assets list (don't download):
```bash
python album_downloader.py https://your-immich-server.com YOUR_API_KEY "Album Name" --list-only
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

Create a key under Account settings > API Keys. A key with the `all` permission still works. Otherwise grant:

- Downloader: `server.about`, `user.read`, `asset.read`, `asset.download`
- Album downloader: those, plus `album.read`
- Album creator: `user.read`, `asset.read`, `album.read`, `album.create`, `albumAsset.create`
- Deleter: `user.read`, `asset.delete`

The album creator turns each folder in your external library into an album you own. Pass the library import path exactly as Immich stores it in `originalPath`. A partner's library, generated encoded-video files, and files outside that path are skipped. Assets already in any album are left alone. A folder name that matches an album shared by someone else creates your own album instead of updating theirs.

### Output

- Downloaded files are stored in `download/data/` folder
- Assets list is saved as `assets_to_download.json` in the `download/` folder
- Original filenames are preserved
