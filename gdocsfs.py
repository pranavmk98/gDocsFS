#!/usr/bin/env python

from __future__ import with_statement

import os
import sys
import errno
import gdoc

from collections import defaultdict
from fuse import FUSE, FuseOSError, Operations
from stat import S_IFDIR, S_IFLNK, S_IFREG
from time import time

# Toggle debug mode
DEBUG = False

class GDocsFS(Operations):
    def __init__(self, root):
        self.root = root
        self.files = {}

        # Dict: file path -> document ID (did)
        self.path_dids = {}

        # Dict: file descriptor -> document ID (did)
        self.fd_dids = {}

        # New stuff
        self.data = {}
        self.fd = 3
        now = time()
        self.files['/'] = {}

        # Each file maps to an attribute dict and a subdirs dict
        self.files['/']['subdirs'] = {}
        self.files['/']['attr'] = dict(
            st_mode=(S_IFDIR | 0o755),
            st_ctime=now,
            st_mtime=now,
            st_atime=now,
            st_nlink=2
        )

    # Helpers
    # =======

    def _full_path(self, partial):
        if partial.startswith("/"):
            partial = partial[1:]
        path = os.path.join(self.root, partial)
        return path

    # Given a path to a file, traverses down and returns the dict associated
    # with the given file
    def _get_file_dict(self, path, files):
        assert(path != '')
        # if path == '':
            # return files

        if path == '/':
            return files['/']
        if path[0] == '/':
            return self._get_file_dict(path[1:], files['/']['subdirs'])

        folders = path.split('/')

        if len(folders) == 1:
            if folders[0] not in files:
                raise FuseOSError(errno.ENOENT)
            return files[folders[0]]

        # Construct new path with top level dir removed
        path = [x for x in folders if x != '']
        new_path = '/'.join(path[1:])
        curr_file = path[0]

        if curr_file not in files:
            raise FuseOSError(errno.ENOENT)
        new_files = files[curr_file]['subdirs']
        return self._get_file_dict(new_path, new_files)

    # Updates nlink values of every directory along path by given amount
    def _update_nlinks(self, path, files, delta):
        # Should not be called on root
        assert(path != '/')

        if path == '':
            return

        folders = path.split('/')
        if len(folders) == 1:
            if folders[0] not in files:
                raise FuseOSError(errno.ENOENT)
            files[folders[0]]['attr']['st_nlink'] += delta
            return

        # Construct new path with top level dir removed
        path = [x for x in path if x != '']
        new_path = '/'.join(path[1:])
        curr_file = path[0]

        if curr_file not in files:
            raise FuseOSError(errno.ENOENT)

        # Update nlink
        files[curr_file]['attr']['st_nlink'] += delta

        # Recurse
        return self._update_nlinks(new_path, files, delta)

    # Generate dict for dir
    def _gen_dict(self, mode):
        d = {}
        d['attr'] = dict(
            st_mode=(S_IFDIR | mode),
            st_nlink=2,
            st_size=0,
            st_ctime=time(),
            st_mtime=time(),
            st_atime=time(),
        )
        d['subdirs'] = {}
        return d

    # Recursive mkdir
    # TODO: handle errno for dirs which already exist (don't throw err for calls
    # to this function from create())
    def _mkdir_helper(self, path, files, mode):
        # Should not create root
        if path == '/':
            return files

        if path == '':
            return files

        folders = path.split('/')
        if len(folders) == 1:
            if folders[0] not in files:
                files[folders[0]] = self._gen_dict(mode)
            else:
                files[folders[0]]['attr']['st_nlink'] += 1
            return files
        # return files

        # Construct new path with top level dir removed
        path = [x for x in folders if x != '']
        new_path = '/'.join(path[1:])
        curr_file = path[0]

        if curr_file not in files:
            files[curr_file] = self._gen_dict(mode)
        else:
            # If the dir already exists, increase nlink
            files[curr_file]['attr']['st_nlink'] += 1

        new_files = files[curr_file]['subdirs']
        added = self._mkdir_helper(new_path, new_files, mode)
        files[curr_file]['subdirs'] = added
        # print('Returning', files)
        return files

    # Filesystem methods
    # ==================

    def access(self, path, mode):
        return
        print('access', path)
        full_path = self._full_path(path)
        if not os.access(full_path, mode):
            raise FuseOSError(errno.EACCES)
        print('done access')

    def chmod(self, path, mode):
        print('chmod')
        file_info = self._get_file_dict(path, self.files)
        file_info['attr']['st_mode'] &= 0o770000
        file_info['attr']['st_mode'] |= mode
        return 0

    def chown(self, path, uid, gid):
        print('chown')
        file_info = self._get_file_dict(path, self.files)
        file_info['attr']['st_uid'] = uid
        file_info['attr']['st_gid'] = gid

    def getattr(self, path, fh=None):
        # print('getattr', path)
        # print(self.files)
        file_info = self._get_file_dict(path, self.files)
        # if path not in self.files:
            # raise FuseOSError(errno.ENOENT)
        return file_info['attr']

    def readdir(self, path, fh):
        print('readdir', path)
        file_info = self._get_file_dict(path, self.files)
        return ['.', '..'] + [x for x in file_info['subdirs']]

    def readlink(self, path):
        print('readlink')
        return self.data[path]

    def rmdir(self, path):
        print('rmdir')
        assert(path != '/')

        # with multiple level support, need to raise ENOTEMPTY if contains any files
        file_info = self._get_file_dict(path, self.files)
        if len(file_info['subdirs'].keys()) > 0:
            raise FuseOSError(errno.ENOTEMPTY)

        # Get rid of the last file in the path
        path_minus_one = '/' + '/'.join([x for x in path.split('/') if x != ''][:-1])
        dir_to_delete = [x for x in path.split('/') if x != ''][-1]
        assert(path_minus_one != '')
        file_info = self._get_file_dict(path_minus_one, self.files)
        file_info['subdirs'].pop(dir_to_delete)

        # Update nlinks
        self.files['/']['attr']['st_nlink'] -= 1
        self._update_nlinks(path_minus_one[1:], self.files, -1)

    def mkdir(self, path, mode):
        print('mkdir', path)

        # Create the dirs
        self.files['/']['subdirs'] = self._mkdir_helper(path[1:], self.files['/']['subdirs'], mode)

        # Update nlink of root
        self.files['/']['attr']['st_nlink'] += 1
        # print(self.files)

    def statfs(self, path):
        print('statfs')
        return dict(f_bsize=512, f_blocks=4096, f_bavail=2048)

    def unlink(self, path):
        print('unlink', path)
        if path in self.data:
            self.data.pop(path)

        dirs = path.split('/')[1:]
        files = self.files['/']['subdirs']
        for i in dirs[:-1]:
            if i != '':
                files = files[i]['subdirs']
        if dirs[-1] in files:
            files.pop(dirs[-1])

        if path in self.path_dids:
            doc_id = self.path_dids[path]
            gdoc.delete_doc(doc_id)

    def symlink(self, target, source):
        print('symlink', target, source)
        self.mkdir(target, 0o777)
        file_info = self._get_file_dict(target, self.files)
        file_info['attr'] = dict(
            st_mode=(S_IFLNK | 0o777),
            st_nlink=1,
            st_size=len(source)
        )

        self.data[target] = source

    # TODO: implement rename with new updated heirarchical file structure
    def rename(self, old, new):
        print('rename', old, new)
        if old in self.data:
            self.data[new] = self.data.pop(old)
        if old in self.files:
            self.files[new] = self.files.pop(old)

    def utimens(self, path, times=None):
        print('utimens')
        now = time()
        atime, mtime = times if times else (now, now)

        file_info = self._get_file_dict(path, self.files)
        file_info['attr']['st_atime'] = atime
        file_info['attr']['st_mtime'] = mtime

    # File methods
    # ============

    def open(self, path, flags):
        print('open', path, oct(flags))
        self.fd += 1

        doc_id = self.path_dids[path]
        self.fd_dids[self.fd] = doc_id
        return self.fd

    def create(self, path, mode):
        print('create', path)
        assert(path != '/')
        # Create a new document
        doc_id = gdoc.create_doc(path)

        # Map path -> document ID
        self.path_dids[path] = doc_id

        # Get path to file
        folders = path.split('/')
        path_minus_one = '/' + '/'.join([x for x in folders if x != ''][:-1])
        file_to_create = [x for x in folders if x != ''][-1]

        # Create dir till file, add files attributes
        self.files['/']['subdirs'] = self._mkdir_helper(path_minus_one[1:], self.files['/']['subdirs'], mode)
        assert(path_minus_one != '')
        file_info = self._get_file_dict(path_minus_one, self.files)

        new_file = {}
        new_file['attr'] = dict(
            st_mode=(S_IFREG | mode),
            st_nlink=1,
            st_size=0,
            st_ctime=time(),
            st_mtime=time(),
            st_atime=time()
        )

        file_info['subdirs'][file_to_create] = new_file
        print(self.files)

        self.fd += 1
        self.fd_dids[self.fd] = doc_id
        return self.fd

    def read(self, path, length, offset, fh):
        print('read', offset, path)

        if fh not in self.fd_dids:
            return FuseOSError(errno.EBADF)

        # Get the doc ID
        doc_id = self.fd_dids[fh]
        string, _ = gdoc.read_doc(doc_id, offset, length)
        return string

    def write(self, path, buf, offset, fh):
        print('write', offset, path)

        if fh not in self.fd_dids:
            return FuseOSError(errno.EBADF)

        # Get the doc ID
        doc_id = self.fd_dids[fh]
        gdoc.write_doc(doc_id, offset, buf)

        assert(path != '')
        file_info = self._get_file_dict(path, self.files)
        file_info['attr']['st_size'] += len(buf)

        return len(buf)

    def truncate(self, path, length, fh=None):
        print('truncate')

        # Get the current content
        doc_id = self.path_dids[path]
        curr_content, _ = gdoc.read_doc(doc_id, 0, None)

        # Make sure extending the file fills it in with zero bytes
        null = bytes([0])
        new_content = curr_content.ljust(length, null)
        # Write the new truncated content
        gdoc.write_doc(doc_id, 0, new_content)

        assert(path != '')
        file_info = self._get_file_dict(path, self.files)
        file_info['attr']['st_size'] = length

    # No buffers so no need for this function
    def flush(self, path, fh):
        print('flush')
        return

    def release(self, path, fh):
        print('release')
        # Remove fd -> doc ID mapping and close fd
        self.fd_dids[fh] = None

    def fsync(self, path, fdatasync, fh):
        print('fsync')
        return self.flush(path, fh)


def main(mountpoint):
    # Initialize gDocs services
    gdoc.initialize()

    # Run filesystem
    FUSE(GDocsFS(mountpoint), mountpoint, nothreads=True, foreground=True, debug=DEBUG)

if __name__ == '__main__':
    main(sys.argv[1])
