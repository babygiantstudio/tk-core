"""
Copyright (c) 2012 Shotgun Software, Inc
----------------------------------------------------

Shotgun utilities

"""

import os

from tank_vendor.shotgun_api3 import Shotgun
from tank_vendor import yaml

from .. import root
from ..errors import TankError
from ..platform import constants
from . import login


def __create_sg_connection(shotgun_cfg_path, evaluate_script_user):
    """
    Creates a standard tank shotgun connection.
    """

    if not os.path.exists(shotgun_cfg_path):
        raise TankError("Could not find shotgun configuration file '%s'!" % shotgun_cfg_path)

    # load the config file
    try:
        with open(shotgun_cfg_path) as open_file:
            config_data = yaml.load(open_file)
    except Exception, error:
        raise TankError("Cannot load config file '%s'. Error: %s" % (shotgun_cfg_path, error))

    # validate the config file
    if "host" not in config_data:
        raise TankError("Missing required field 'host' in config '%s'" % shotgun_cfg_path)
    if "api_script" not in config_data:
        raise TankError("Missing required field 'api_script' in config '%s'" % shotgun_cfg_path)
    if "api_key" not in config_data:
        raise TankError("Missing required field 'api_key' in config '%s'" % shotgun_cfg_path)
    if "http_proxy" not in config_data:
        http_proxy = None
    else:
        http_proxy = config_data["http_proxy"]

    # create API
    sg = Shotgun(config_data["host"],
                 config_data["api_script"],
                 config_data["api_key"],
                 http_proxy=http_proxy)

    script_user = None

    if evaluate_script_user:
        # determine the script user running currently
        # get the API script user ID from shotgun
        script_user = sg.find_one("ApiUser",
                                          [["firstname", "is", config_data["api_script"]]],
                                          fields=["type", "id"])
        if script_user is None:
            raise TankError("Could not evaluate the current Tank App Store User! Please contact support.")

    return (sg, script_user)

def create_sg_connection(proj_root):
    """
    Creates a standard tank shotgun connection.
    """
    studio_root = os.path.abspath(os.path.join(proj_root, ".."))
    shotgun_cfg_path = os.path.join(studio_root, "tank", "config", "core", constants.SHOTGUN_CONFIG_FILE)
    api_handle, _ = __create_sg_connection(shotgun_cfg_path, evaluate_script_user=False)
    return api_handle

def create_sg_connection_studio_root(studio_root):
    """
    Creates a standard tank shotgun connection.
    based on the studio root
    """
    shotgun_cfg_path = os.path.join(studio_root, "tank", "config", "core", constants.SHOTGUN_CONFIG_FILE)
    api_handle, _ = __create_sg_connection(shotgun_cfg_path, evaluate_script_user=False)
    return api_handle

def create_sg_app_store_connection_proj_root(proj_root):
    """
    Creates a shotgun connection to the tank app store.

    returns a tuple: (api_handle, script_user_entity)

    The second part of the tuple represents the
    user that was used to connect to the app store,
    as a standard sg entity dictionary.
    """
    studio_root = os.path.abspath(os.path.join(proj_root, ".."))
    shotgun_cfg_path = os.path.join(studio_root, "tank", "config", "core", constants.APP_STORE_CONFIG_FILE)
    (api_handle, script_user) = __create_sg_connection(shotgun_cfg_path, evaluate_script_user=True)
    return (api_handle, script_user)

def create_sg_app_store_connection(studio_root):
    """
    Creates a shotgun connection to the tank app store.

    returns a tuple: (api_handle, script_user_entity)

    The second part of the tuple represents the
    user that was used to connect to the app store,
    as a standard sg entity dictionary.

    """
    shotgun_cfg_path = os.path.join(studio_root, "tank", "config", "core", constants.APP_STORE_CONFIG_FILE)
    (api_handle, script_user) = __create_sg_connection(shotgun_cfg_path, evaluate_script_user=True)
    return (api_handle, script_user)


def _make_dep_cache_path(tk, path):
    """
    Makes a path platform agnostic and project relative,
    suitable for storing in the dependency cache field
    """

    # note! Have to take into account that certain applications
    # use forward slashes in their paths even on windows so cannot
    # rely on os.sep

    studio_root = os.path.dirname(tk.project_path)
    studio_root_agnostic = studio_root.replace(os.path.sep, "/")

    path_agnostic = path.replace(os.path.sep, "/")

    # chop off root + leading slash to create path agnostic field
    path_cache = path_agnostic.replace(studio_root_agnostic + "/", "")

    return path_cache

def find_publish(tk, list_of_paths, filters=None, fields=None):
    """
    Finds publishes in Shotgun given paths on disk.
    This method is similar to the find method in the Shotgun API,
    except that instead of an Entity type, a list of files is
    passed into the function.

    In addition to a list of files, shotgun filters can also be specified.
    This may be useful if for example all publishes with a certain status
    should be retrieved.

    By default, the shotgun id is returned for each successfully identified path.
    If you want to retrieve additional fields, you can specify these using
    the fields parameter.

    The method will return a dictionary, keyed by path. The value will be
    a standard shotgun query result dictionary, for example

    {
        "/foo/bar" : { "id": 234, "code": "some data" },
        "/foo/baz" : { "id": 23,  "code": "some more data" }
    }

    Fields that are not found, or filtered out by the filters parameter,
    are not returned in the dictionary.

    :param tk: Tank API Instance
    :param list_of_paths: List of full paths for which information should be retrieved
    :param filters: Optional list of shotgun filters to apply.
    :param fields: Optional list of fields from the matched entities to
                   return. Defaults to id, created_at, and path_cache.
    :returns: dictionary keyed by path
    """
    # Map path caches to full paths, grouped by storage
    # in case of sequences, there will be more than one file
    # per path cache
    # {<storage name>: { path_cache: [full_path, full_path]}}
    storages_paths = _group_by_storage(tk, list_of_paths)
    
    filters = filters or []
    fields = fields or []
    fields.append("created_at")
    fields.append("path_cache")

    # Use storage, path_cache and filters to find publishes grouped by storage.
    published_files = _publishes_from_paths(tk, storages_paths, filters, fields)

    # Use mapping of path_cache to full paths to create mapping of 
    # full paths to publishes.
    matches = _sort_publishes(published_files, storages_paths) 
    return matches


def _group_by_storage(tk, list_of_paths):
    """
    Groups paths by local storage (root).
    """
    storages_paths = {}

    for path in list_of_paths:

        # use abstracted path if path is part of a sequence
        abstract_path = _check_for_sequence_path(tk, path)
        root_name, dep_path_cache = _calc_path_cache(tk.project_path, abstract_path)

        # make sure that the path is even remotely valid, otherwise skip
        if dep_path_cache is None:
            continue

        # Find LocalStorage matching root name
        # 'primary' root is 'Tank' storage
        if root_name == "primary":
            root_name = "Tank"

        # Update data for this storage
        storage_info = storages_paths.get(root_name, {})
        paths = storage_info.get(dep_path_cache, [])
        paths.append(path)
        storage_info[dep_path_cache] = paths
        storages_paths[root_name] = storage_info

    return storages_paths


def _publishes_from_paths(tk, storages_paths, filters=[], fields=[]):
    # make copy
    sg_fields = fields[:]

    # query for each storage
    published_files = {}
    for root_name, storage_info in storages_paths.items():
        local_storage = tk.shotgun.find_one("LocalStorage", [["code", "is", root_name]])

        if not local_storage:
            raise TankError("Unable to locate LocalStorage matching root name %s." % root_name +
                           " Ensure that all project roots defined in the project's roots file" +
                           " have matching LocalStorage's set up in Shotgun.")

        # make copy
        sg_filters = filters[:]
        path_cache_filter = ["path_cache", "in"]
        for path_cache_path in storage_info:
            path_cache_filter.append(path_cache_path)

        sg_filters.append(path_cache_filter)
        sg_filters.append( ["path_cache_storage", "is", local_storage] )

        published_files[root_name] = tk.shotgun.find("TankPublishedFile", sg_filters, sg_fields)
    return published_files

def _sort_publishes(published_files, storage_paths):
    """maps absolute file paths to published file entities."""
    matches = {}
    for root_name, publishes in published_files.items():
        storage_info = storage_paths[root_name]
        for publish in publishes:
            path_cache = publish["path_cache"]

            for full_path in storage_info.get(path_cache, []):
                cur_publish = matches.get(full_path, publish)
                # We want the most recent
                if not cur_publish["created_at"] > publish["created_at"]:
                    matches[full_path] = publish

    return matches


def register_publish(tk, context, path, name, version_number, **kwargs):
    """
    Creates a Tank Published File in Shotgun.

    Required parameters:

        tk - a Tank API instance

        context - the context we want to associate with the publish

        path - the path to the file or sequence we want to publish. If the
               path is a sequence path it will be abstracted so that
               any sequence keys are replaced with their default values.

        name - a name, without version number, which helps distinguish
               this publish from other publishes. This is typically
               used for grouping inside of Shotgun so that all the
               versions of the same "file" can be grouped into a cluster.
               For example, for a maya publish, where we track only
               the scene name, the name would simply be that: the scene
               name. For something like a render, it could be the scene
               name, the name of the AOV and the name of the render layer.

        version_number - the verison numnber of the item we are publishing.

    Optional arguments:

        task - a shotgun entity dictionary with id and type (which should always be Task).
               if no value is specified, the task will be grabbed from the context object.

        comment - a string containing a description of the comment

        thumbnail_path - a path to a thumbnail (png or jpeg) which will be uploaded to shotgun
                         and associated with the publish.

        dependency_paths - a list of file system paths that should be attempted to be registered
                           as dependencies. Files in this listing that do not appear as publishes
                           in shotgun will be ignored.

        tank_type - a tank type in the form of a string which should match a tank type
                    that is registered in Shotgun.

        update_entity_thumbnail - push thumbnail up to the attached entity

        update_task_thumbnail - push thumbnail up to the attached task

    Future:
    - error handling
    - look at a project level config to see if publish should succeed if Shotgun is down?
    - if Shotgun is down, log to sqlite and try again later?
    """

    task = context.task or kwargs.get("task")
    thumbnail_path = kwargs.get("thumbnail_path")
    comment = kwargs.get("comment")
    dependency_paths = kwargs.get('dependency_paths', [])
    tank_type = kwargs.get('tank_type')
    update_entity_thumbnail = kwargs.get("update_entity_thumbnail", False)
    update_task_thumbnail = kwargs.get("update_task_thumbnail", False)

    path = _check_for_sequence_path(tk, path)

    sg_tank_type = None
    # query shotgun for the tank_type
    if tank_type:
        if not isinstance(tank_type, basestring):
            raise TankError('tank_type must be a string')

        filters = [
            ['code', 'is', tank_type],
            ['project', 'is', context.project]
        ]
        sg_tank_type = tk.shotgun.find_one(
            'TankType',
            filters=filters
        )

        if not sg_tank_type:
            raise TankError("TankType '%s' not found." % (tank_type))

    # create the publish
    entity = _create_published_file(tk, context, path, name, version_number, task, comment, sg_tank_type)

    # upload thumbnails
    if thumbnail_path and os.path.exists(thumbnail_path):

        # publish
        tk.shotgun.upload_thumbnail("TankPublishedFile", entity["id"], thumbnail_path)

        # entity
        if update_entity_thumbnail == True and context.entity is not None:
            tk.shotgun.upload_thumbnail(context.entity["type"],
                                        context.entity["id"],
                                        thumbnail_path)

        # task
        if update_task_thumbnail == True and task is not None:
            tk.shotgun.upload_thumbnail("Task", task["id"], thumbnail_path)


    # register dependencies
    _create_dependencies(tk, entity, dependency_paths)

    return entity

def _check_for_sequence_path(tk, path):
    template = tk.template_from_path(path)
    if template:
        abstract_keys = template.abstract_keys()
        if abstract_keys:
            # we want to use the default values for abstract keys
            cur_fields = template.get_fields(path)
            for abstract_key in abstract_keys:
                del(cur_fields[abstract_key])
            path = template.apply_fields(cur_fields)
    return path

def _create_dependencies(tk, entity, dependency_paths):
    publishes = find_publish(tk, dependency_paths)
    
    for dependency_path in dependency_paths:
        published_file = publishes.get(dependency_path)
        if published_file:
            data = { "tank_published_file": entity,
                     "dependent_tank_published_file": published_file }

            tk.shotgun.create('TankDependency', data)


def _create_published_file(tk, context, path, name, version_number, task, comment, tank_type):
    # Make path platform agnostic.
    _, path_cache = _calc_path_cache(tk.project_path, path)

    data = {
        "code": os.path.basename(path),
        "description": comment,
        "name": name,
        "project": context.project,
        "entity": context.entity,
        "task": task,
        "version_number": version_number,
        "path": { "local_path": path },
        "path_cache": path_cache,
    }

    sg_user = login.get_shotgun_user(tk.shotgun)
    if sg_user:
        data["created_by"] = sg_user

    if tank_type:
        data['tank_type'] = tank_type

    return tk.shotgun.create("TankPublishedFile", data)

def _calc_path_cache(project_root, path):
    """
    Calculates root path name and relative path (including project directory).
    returns (root_name, path_cache)

    If the location cannot be computed, because the path does not belong
    to a valid root, (None, None) is returned.
    """
    # paths may be c:/foo in maya on windows - don't rely on os.sep here!

    # normalize input path first c:\foo -> c:/foo
    norm_path = path.replace(os.sep, "/")

    # get roots - don't assume data is reurned on any partiuclar form
    # may return c:\foo, c:/foo or /foo - assume that we need to normalize this path
    roots = root.get_project_roots(project_root)

    for root_name, root_path in roots.items():
        norm_root_path = root_path.replace(os.sep, "/")

        if norm_path.lower().startswith(norm_root_path.lower()):
            norm_parent_dir = os.path.dirname(norm_root_path)
            # remove parent dir plus "/"
            path_cache = norm_path[ len(norm_parent_dir) + 1: ]
            return root_name, path_cache
    # not found, return None values
    return None, None
