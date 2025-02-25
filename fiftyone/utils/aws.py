"""
Utilities for working with
`Amazon Web Services <https://aws.amazon.com/>`
S3 storage buckets.

| Copyright 2017-2021, Voxel51, Inc.
| `voxel51.com <https://voxel51.com/>`_
|
"""
import logging
import multiprocessing
import multiprocessing.dummy
import os
from urllib.parse import urlparse

import boto3
import botocore

import fiftyone.core.utils as fou

import eta.core.utils as etau


logger = logging.getLogger(__name__)


def download_public_s3_files(
    urls, download_dir=None, num_workers=None, overwrite=True,
):
    """Download files from a public AWS S3 bucket using unsigned urls.

    The `url` argument either accepts:

        * A list of paths to objects in the s3 bucket::

            urls = ["s3://bucket_name/dir1/file1.ext", ...]

          When `urls` is a list, then the `download_dir` argument is required
          and all objects will be downloaded into that directory

        * A dictionary mapping the paths of objects to files on disk
          to store each object::

            urls = {
                "s3://bucket_name/dir1/file1.ext": "/path/to/local/file1.ext",
                ...
            }

    Args:
        urls: either a list of urls to objects in an s3 bucket, or a dict
            mapping these urls to locations on disk. If `urls` is a list, then
            the `download_dir` argument is required
        download_dir (None): the directory to store all downloaded objects.
            This is only used if `urls` is a list
        num_workers (None): the number of processes to use when downloading
            files. By default, ``multiprocessing.cpu_count()`` is used
        overwrite (True): whether to overwrite existing files
    """
    if isinstance(urls, list):
        if download_dir is None:
            raise ValueError(
                "When `urls` is a list, `download_dir` is required but was found to be `None`."
            )
        urls = {url: None for url in urls}

    if download_dir:
        etau.ensure_dir(download_dir)

    if num_workers is None or num_workers < 1:
        num_workers = multiprocessing.cpu_count()

    s3_client = boto3.client(
        "s3",
        config=botocore.config.Config(
            signature_version=botocore.UNSIGNED,
            max_pool_connections=max(10, num_workers),
        ),
    )

    inputs = _build_inputs(
        urls, s3_client, download_dir=download_dir, overwrite=overwrite
    )

    if not inputs:
        return

    if num_workers == 1:
        _single_thread_download(inputs)
    else:
        _multi_thread_download(inputs, num_workers)


def _build_inputs(urls, s3_client, download_dir=None, overwrite=True):
    inputs = []
    for url, filepath in urls.items():
        bucket_name, object_path = _parse_url(url)
        if filepath is None:
            filepath = os.path.join(download_dir, object_path)
        if not os.path.isfile(filepath):
            inputs.append((bucket_name, object_path, filepath, s3_client))
        else:
            if overwrite:
                os.remove(filepath)
            else:
                logger.warning(
                    "File `%s` already exists, skipping..." % filepath
                )

    return inputs


def _parse_url(url):
    result = urlparse(url, allow_fragments=False)
    return result.netloc, result.path.lstrip("/")


def _single_thread_download(inputs):
    with fou.ProgressBar(total=len(inputs), iters_str="files") as pb:
        for bucket_name, obj, filepath, s3_client in pb(inputs):
            s3_client.download_file(bucket_name, obj, filepath)


def _multi_thread_download(inputs, num_workers):
    with fou.ProgressBar(total=len(inputs), iters_str="files") as pb:
        with multiprocessing.dummy.Pool(num_workers) as pool:
            for _ in pool.imap_unordered(_do_s3_download, inputs):
                pb.update()


def _do_s3_download(args):
    bucket_name, obj, filepath, s3_client = args
    s3_client.download_file(bucket_name, obj, filepath)
