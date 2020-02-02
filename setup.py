from setuptools import setup, find_packages

setup(
    name='ml-somnam',
    version='0.1.0',
    author='Tomek Miodek',
    author_email='tomek.miodek@gmail.com',
    description='Library scraper scripts',
    packages=find_packages(),
    url='https://github.com/somnam/ml',
    entry_points={
        'console_scripts': [
            'shelf_scraper=libexec.shelf_scraper:run',
            'library_scraper=libexec.shelf_scraper:run',
        ],
    },
)
