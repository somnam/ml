import click
import logging.config
from lib.shelf_scraper import CLIShelfScraper
from lib.common import get_file_path

logging.config.fileConfig(get_file_path('etc', 'config.ini'))


@click.command()
@click.pass_context
@click.option('--profile-name', help='Profile name (required)')
@click.option('--shelf-name', help='Shelf name to search (required)')
@click.option('--include-price', is_flag=True, default=False,
              help='Append price to books')
def run(context, profile_name, shelf_name, include_price):
    # Display help message when no arguments given.
    if not(profile_name and shelf_name):
        click.echo(context.get_help(), color=context.color)
        return

    CLIShelfScraper(profile_name=profile_name,
                    shelf_name=shelf_name,
                    include_price=include_price).run()


if __name__ == '__main__':
    run()
