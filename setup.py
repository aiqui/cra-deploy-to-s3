from setuptools import setup, find_packages

# More can be added, follow this:
# https://packaging.python.org/tutorials/packaging-projects/
setup(
    name="s3-deploy",
    version='0.1',
    license='MIT',
    install_requires=['boto3'],
    packages=find_packages()
)
