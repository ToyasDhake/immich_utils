import argparse
import json
from typing import Any
import structlog
from downloader import is_generated_file
from immich_client import ImmichClient


logger = structlog.get_logger()


def chunk_list_for_loop(data_list: list[str], chunk_size: int) -> list[list[str]]:
    result_chunks = []
    for i in range(0, len(data_list), chunk_size):
        result_chunks.append(data_list[i:i + chunk_size])
    return result_chunks


def skip_reason(asset: dict[str, Any], user_id: str) -> str | None:
    """Return why this asset must stay on the server, or None if it can be trashed.

    Only a verified download of the API key owner's own upload is eligible.
    Partner assets, external-library files, and generated motion clips are left
    alone even if an older list included them.
    """
    if asset.get('integrity') != 'verified':
        return 'unverified'
    if not asset.get('id'):
        return 'missing id'
    if asset.get('ownerId') != user_id:
        return 'partner'
    if asset.get('libraryId'):
        return 'external library'
    if is_generated_file(asset):
        return 'generated'
    return None


def trash_chunk(client: ImmichClient, asset_ids: list[str]) -> tuple[int, int]:
    """Move assets to the trash. force stays false, so files are not removed yet.

    Immich rejects a whole batch when any id in it cannot be trashed. On that
    failure, retry one asset at a time so the rest of the batch still moves.
    """
    if client.delete_assets(asset_ids, force=False):
        return len(asset_ids), 0

    logger.warning(f'Batch of {len(asset_ids)} failed, retrying each asset')
    trashed = 0
    failed = 0
    for asset_id in asset_ids:
        if client.delete_assets([asset_id], force=False):
            trashed += 1
        else:
            failed += 1
    return trashed, failed


def main(args: argparse.Namespace) -> None:
    client = ImmichClient(args.server_url, args.api_key)
    user_id = client.get_current_user_id()
    if user_id is None:
        logger.error('Cannot trash assets without the current user id')
        return

    with open(args.deletion_file) as f:
        assets = json.load(f)

    skipped: dict[str, int] = {}
    deletion_ids: list[str] = []
    seen: set[str] = set()
    for asset in assets:
        reason = skip_reason(asset, user_id)
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        asset_id = asset['id']
        if asset_id in seen:
            continue
        seen.add(asset_id)
        deletion_ids.append(asset_id)

    for reason, count in sorted(skipped.items()):
        logger.info(f'Skipping {count} {reason} assets')
    logger.info(f'Found {len(deletion_ids)} assets to move to trash')

    if not deletion_ids:
        return

    trashed = 0
    failed = 0
    chunks = chunk_list_for_loop(deletion_ids, 100)
    for i, chunk in enumerate(chunks, 1):
        logger.debug(f'Moving chunk [{i}/{len(chunks)}] to trash')
        chunk_trashed, chunk_failed = trash_chunk(client, chunk)
        trashed += chunk_trashed
        failed += chunk_failed

    logger.info(f'Moved {trashed} assets to trash from {args.deletion_file}')
    if failed:
        logger.error(f'Failed to trash {failed} assets')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Move downloaded and verified assets to the Immich trash')
    parser.add_argument('server_url', help='Immich server URL (e.g., https://immich.example.com)')
    parser.add_argument('api_key', help='API key with full access')
    parser.add_argument('--deletion_file', default='downloads/downloaded_assets.json',
            help='File with list of asset IDs to delete')

    args = parser.parse_args()

    main(args)
