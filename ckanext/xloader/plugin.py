# encoding: utf-8

import logging

from ckan.plugins.toolkit import config
import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit

from ckanext.xloader import action, auth
import ckanext.xloader.helpers as xloader_helpers
from ckanext.xloader.loader import fulltext_function_exists, get_write_engine

log = logging.getLogger(__name__)


# resource.formats accepted by ckanext-xloader. Must be lowercase here.
DEFAULT_FORMATS = [
    "csv",
    "application/csv",
    "xls",
    "xlsx",
    "tsv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ods",
    "application/vnd.oasis.opendocument.spreadsheet",
]


class XLoaderFormats(object):
    formats = None

    @classmethod
    def is_it_an_xloader_format(cls, format_):
        if cls.formats is None:
            cls._formats = config.get("ckanext.xloader.formats")
            if cls._formats is not None:
                cls._formats = cls._formats.lower().split()
            else:
                cls._formats = DEFAULT_FORMATS
        if not format_:
            return False
        return format_.lower() in cls._formats


class xloaderPlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IConfigurable)
    plugins.implements(plugins.IResourceUrlChange)
    plugins.implements(plugins.IActions)
    plugins.implements(plugins.IAuthFunctions)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IResourceController, inherit=True)

    if toolkit.check_ckan_version("2.9"):
        plugins.implements(plugins.IClick)
        plugins.implements(plugins.IBlueprint)

        # IClick
        def get_commands(self):
            from ckanext.xloader.cli import get_commands

            return get_commands()

        # IBlueprint
        def get_blueprint(self):
            from ckanext.xloader.views import get_blueprints

            return get_blueprints()

    else:
        plugins.implements(plugins.IRoutes, inherit=True)

        # IRoutes
        def before_map(self, m):
            m.connect(
                "xloader.resource_data",
                "/dataset/{id}/resource_data/{resource_id}",
                controller="ckanext.xloader.controllers:ResourceDataController",
                action="resource_data",
                ckan_icon="cloud-upload",
            )
            return m

    # IConfigurer

    def update_config(self, config):
        templates_base = config.get(
            "ckan.base_templates_folder", "templates-bs2"
        )  # for ckan < 2.8
        toolkit.add_template_directory(config, templates_base)

    # IConfigurable

    def configure(self, config_):
        if config_.get("ckanext.xloader.ignore_hash") in ["True", "TRUE", "1", True, 1]:
            self.ignore_hash = True
        else:
            self.ignore_hash = False

        for config_option in ("ckan.site_url",):
            if not config_.get(config_option):
                raise Exception(
                    "Config option `{0}` must be set to use ckanext-xloader.".format(
                        config_option
                    )
                )

        if toolkit.check_ckan_version(max_version="2.7.99"):
            # populate_full_text_trigger() needs to be defined, and this was
            # introduced in CKAN 2.8 when you installed datastore e.g.:
            #     paster datastore set-permissions
            # However before CKAN 2.8 we need to check the user has defined
            # this function manually.
            connection = get_write_engine().connect()
            if not fulltext_function_exists(connection):
                raise Exception(
                    "populate_full_text_trigger is not defined. "
                    "See ckanext-xloader's README.rst for more "
                    "details."
                )

    # IResourceUrlChange

    def notify(self, resource):
        context = {
            "ignore_auth": True,
        }
        resource_dict = toolkit.get_action("resource_show")(
            context,
            {
                "id": resource.id,
            },
        )
        self._submit_to_xloader(resource_dict)

    # IResourceController
    if toolkit.check_ckan_version("2.10"):

        def after_resource_create(self, context, resource_dict):
            self._submit_to_xloader(resource_dict)

        def before_resource_show(self, resource_dict):
            resource_dict[
                "datastore_contains_all_records_of_source_file"
            ] = toolkit.asbool(
                resource_dict.get("datastore_contains_all_records_of_source_file")
            )

    else:

        def after_create(self, context, resource_dict):
            self._submit_to_xloader(resource_dict)

        def before_show(self, resource_dict):
            resource_dict[
                "datastore_contains_all_records_of_source_file"
            ] = toolkit.asbool(
                resource_dict.get("datastore_contains_all_records_of_source_file")
            )

    def _submit_to_xloader(self, resource_dict):
        context = {"ignore_auth": True, "defer_commit": True}
        if not XLoaderFormats.is_it_an_xloader_format(resource_dict["format"]):
            log.debug(
                "Skipping xloading resource {id} because "
                'format "{format}" is not configured to be '
                "xloadered".format(**resource_dict)
            )
            return
        if resource_dict["url_type"] in ("datapusher", "xloader"):
            log.debug(
                "Skipping xloading resource {id} because "
                'url_type "{url_type}" means resource.url '
                "points to the datastore already, so loading "
                "would be circular.".format(**resource_dict)
            )
            return

        try:
            log.debug(
                "Submitting resource %s to be xloadered", resource_dict["id"]
            )
            toolkit.get_action("xloader_submit")(
                context,
                {
                    "resource_id": resource_dict["id"],
                    "ignore_hash": self.ignore_hash,
                },
            )
        except toolkit.ValidationError as e:
            # If xloader is offline, we want to catch error instead
            # of raising otherwise resource save will fail with 500
            log.critical(e)
            pass

    # IActions

    def get_actions(self):
        return {
            "xloader_submit": action.xloader_submit,
            "xloader_hook": action.xloader_hook,
            "xloader_status": action.xloader_status,
        }

    # IAuthFunctions

    def get_auth_functions(self):
        return {
            "xloader_submit": auth.xloader_submit,
            "xloader_status": auth.xloader_status,
        }

    # ITemplateHelpers

    def get_helpers(self):
        return {
            "xloader_status": xloader_helpers.xloader_status,
            "xloader_status_description": xloader_helpers.xloader_status_description,
        }
