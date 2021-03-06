# -*- coding: utf-8 -*-

from couchdb import Server, Session
from base64 import b64encode
from couchdb.http import ResourceConflict
from json import dumps
from libnacl.secret import SecretBox
from logging import getLogger
from openprocurement.api.utils import context_unpack, json_view, APIResource
from pyramid.security import Allow
from pkg_resources import Environment
from itertools import chain
from socket import error

PKG_ENV = Environment()
PKG_VERSIONS = dict(chain.from_iterable([
    [(x.project_name, x.version) for x in PKG_ENV[i]]
    for i in PKG_ENV
]))


LOGGER = getLogger(__package__)


class ConfigError(Exception):
    pass


class Root(object):
    __name__ = None
    __parent__ = None
    __acl__ = [
        (Allow, 'g:archivarius', 'dump_resource'),
        (Allow, 'g:archivarius', 'delete_resource'),
    ]

    def __init__(self, request):
        self.request = request
        self.db = request.registry.db


def prepare_couchdb(couch_url, db_name, logger=LOGGER):
    server = Server(couch_url, session=Session(retry_delays=range(10)))
    try:
        if db_name not in server:
            db = server.create(db_name)
        else:
            db = server[db_name]
    except error as e:
        logger.error('Database error: {}'.format(e.message))
        raise ConfigError(e.strerror)

    #validate_doc = db.get(VALIDATE_BULK_DOCS_ID, {'_id': VALIDATE_BULK_DOCS_ID})
    #if validate_doc.get('validate_doc_update') != VALIDATE_BULK_DOCS_UPDATE:
        #validate_doc['validate_doc_update'] = VALIDATE_BULK_DOCS_UPDATE
        #db.save(validate_doc)
        #logger.info('Validate document update view saved.')
    #else:
        #logger.info('Validate document update view already exist.')
    return db


def delete_resource(request):
    db_doc = request.context
    resource = db_doc.doc_type.lower()
    try:
        _, rev = request.registry.db.save({'_id': db_doc.id, '_rev': db_doc.rev, '_deleted': True})
    except ResourceConflict, e:  # pragma: no cover
        request.errors.add('body', 'data', str(e))
        request.errors.status = 409
    except Exception, e:  # pragma: no cover
        request.errors.add('body', 'data', str(e))
    else:
        LOGGER.info('Deleted {} {}: dateModified {} -> None'.format(resource, db_doc.id, db_doc.dateModified.isoformat()),
                    extra=context_unpack(request, {'MESSAGE_ID': 'delete_resource'}, {'RESULT': rev}))
        return True


def dump_resource(request):
    docservice_key = getattr(request.registry, 'docservice_key', None)
    box = SecretBox(docservice_key.vk)
    data = request.context.serialize()
    json_data = dumps(data)
    encrypted_data = box.encrypt(json_data)
    return b64encode(encrypted_data)


class ArchivariusResource(APIResource):

    def __init__(self, request, context):
        super(ArchivariusResource, self).__init__(request, context)
        self.resource = request.context.doc_type.lower()

    @json_view(permission='dump_resource')
    def get(self):
        """Tender Dump
        """
        self.LOGGER.info('Dumped {} {}'.format(self.resource, self.context.id),
                         extra=context_unpack(self.request, {'MESSAGE_ID': '{}_dumped'.format(self.resource)}))
        return {'data': {self.resource: dump_resource(self.request), 'versions': PKG_VERSIONS}}

    @json_view(permission='delete_resource')
    def delete(self):
        """Delete tender
        """
        if delete_resource(self.request):
            self.LOGGER.info('Deleted {} {}'.format(self.resource, self.context.id),
                             extra=context_unpack(self.request, {'MESSAGE_ID': '{}_deleted'.format(self.resource)}))
            return {'data': {self.resource: dump_resource(self.request), 'versions': PKG_VERSIONS}}
