import argparse
import json
import structlog
from immich_client import ImmichClient


logger = structlog.get_logger()


def chunk_list_for_loop(data_list: list[str], chunk_size: int) -> list[list[str]]:
    result_chunks = []
    for i in range(0, len(data_list), chunk_size):
        result_chunks.append(data_list[i:i + chunk_size])
    return result_chunks


def main(args: argparse.Namespace) -> None:
    client = ImmichClient(args.server_url, args.api_key)

    with open(args.deletion_file) as f:
        assets = json.load(f)

    deletion_ids = [asset['id'] for asset in assets if asset['integrity'] == 'verified']
    logger.info(f'Found {len(deletion_ids)} assets to delete')

    chunks = chunk_list_for_loop(deletion_ids, 100)

    for i, chunk in enumerate(chunks, 1):
        logger.debug(f'Deleting chunk [{i}/{len(chunks)}]')
        client.delete_assets(chunk)

    logger.info(f'Deleted {len(deletion_ids)} assets from file {args.deletion_file}  with asset '
                    f'length {len(assets)} deleted successfully')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Delete downloaded and verified assets from Immich server')
    parser.add_argument('server_url', help='Immich server URL (e.g., https://immich.example.com)')
    parser.add_argument('api_key', help='API key with full access')
    parser.add_argument('--deletion_file', default='downloads/downloaded_assets.json', 
            help='File with list of asset IDs to delete')
    
    args = parser.parse_args()

    main(args)
