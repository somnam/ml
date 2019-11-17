import click
import logging
import logging.config
from lib.library_scraper import CLILibraryScraper
from lib.common import get_file_path
from lib.config import Config

logging.config.fileConfig(get_file_path('etc', 'config.ini'))


@click.command()
@click.pass_context
@click.option('--library-id',
              type=click.Choice(Config()['library_scraper'].getstruct('libraries'),
                                case_sensitive=False),
              help='Library id (required)')
@click.option('--profile-name', help='Profile name (required)')
@click.option('--auth-data', help='Path to Google auth credentials')
@click.option('--refresh', is_flag=True, default=False, help="Refresh shelf books info")
def run(context, library_id, profile_name, auth_data, refresh):
    if not(library_id and profile_name):
        click.echo(context.get_help(), color=context.color)
        return

    CLILibraryScraper(library_id=library_id,
                      profile_name=profile_name,
                      auth_data=auth_data,
                      refresh=refresh).run()


if __name__ == '__main__':
    run()
