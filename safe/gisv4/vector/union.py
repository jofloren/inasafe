# coding=utf-8

"""
Clip and mask a hazard layer.

Issue https://github.com/inasafe/inasafe/issues/3186
"""

import logging
from qgis.core import (
    QGis,
    QgsGeometry,
    QgsFeatureRequest,
    QgsWKBTypes,
    QgsFeature,
    QgsSpatialIndex
)

from safe.utilities.i18n import tr
from safe.common.exceptions import InvalidKeywordsForProcessingAlgorithm
# from safe.definitionsv4.processing import union
from safe.gisv4.vector.tools import create_memory_layer, wkb_type_groups
from safe.utilities.profiling import profile

__copyright__ = "Copyright 2016, The InaSAFE Project"
__license__ = "GPL version 3"
__email__ = "info@inasafe.org"
__revision__ = '$Format:%H$'


LOGGER = logging.getLogger('InaSAFE')


@profile
def union(union_a, union_b, callback=None):
    """Union of two vector layers.

    Note : This algorithm is copied from :
    https://github.com/qgis/QGIS/blob/master/python/plugins/processing/algs/
    qgis/Union.py

    :param union_a: The vector layer for the union.
    :type union_a: QgsVectorLayer

    :param union_b: The vector layer for the union.
    :type union_b: QgsVectorLayer

    :param callback: A function to all to indicate progress. The function
        should accept params 'current' (int), 'maximum' (int) and 'step' (str).
        Defaults to None.
    :type callback: function

    :return: The clip vector layer.
    :rtype: QgsVectorLayer

    .. versionadded:: 4.0
    """
    # To fix
    # output_layer_name = intersection_vector['output_layer_name']
    # processing_step = intersection_vector['step_name']
    output_layer_name = 'clip'
    processing_step = 'Clipping and masking'

    fields = union_a.fields()
    fields.extend(union_b.fields())

    writer = create_memory_layer(
        output_layer_name,
        union_a.geometryType(),
        union_a.crs(),
        fields
    )
    keywords_union_1 = union_a.keywords
    keywords_union_2 = union_b.keywords
    inasafe_fields_union_1 = keywords_union_1['inasafe_fields']
    inasafe_fields_union_2 = keywords_union_2['inasafe_fields']
    inasafe_fields = inasafe_fields_union_1
    inasafe_fields.update(inasafe_fields_union_2)

    writer.keywords = union_a.keywords
    writer.keywords['inasafe_fields'] = inasafe_fields
    writer.keywords['layer_purpose'] = 'aggregate_hazard'

    writer.startEditing()

    # Begin copy/paste from Processing plugin.
    # Please follow their code as their code is optimized.

    out_feature = QgsFeature()
    index_a = QgsSpatialIndex(union_b.getFeatures())
    index_b = QgsSpatialIndex(union_a.getFeatures())

    count = 0
    nElement = 0
    # Todo fix callback
    # nFeat = len(union_a.getFeatures())
    for inFeatA in union_a.getFeatures():
        # progress.setPercentage(nElement / float(nFeat) * 50)
        nElement += 1
        lstIntersectingB = []
        geom = inFeatA.geometry()
        atMapA = inFeatA.attributes()
        intersects = index_a.intersects(geom.boundingBox())
        if len(intersects) < 1:
            try:
                out_feature.setGeometry(geom)
                out_feature.setAttributes(atMapA)
                writer.addFeature(out_feature)
            except:
                # This really shouldn't happen, as we haven't
                # edited the input geom at all
                LOGGER.debug(
                    tr('Feature geometry error: One or more output features '
                       'ignored due to invalid geometry.'))
        else:
            request = QgsFeatureRequest().setFilterFids(intersects)

            engine = QgsGeometry.createGeometryEngine(geom.geometry())
            engine.prepareGeometry()

            for inFeatB in union_b.getFeatures(request):
                count += 1

                atMapB = inFeatB.attributes()
                tmpGeom = inFeatB.geometry()

                if engine.intersects(tmpGeom.geometry()):
                    int_geom = geom.intersection(tmpGeom)
                    lstIntersectingB.append(QgsGeometry(tmpGeom))

                    if not int_geom:
                        # There was a problem creating the intersection
                        LOGGER.debug(
                            tr('GEOS geoprocessing error: One or more input '
                               'features have invalid geometry.'))
                        int_geom = QgsGeometry()
                    else:
                        int_geom = QgsGeometry(int_geom)

                    if int_geom.wkbType() == QgsWKBTypes.Unknown\
                            or QgsWKBTypes.flatType(
                            int_geom.geometry().wkbType()) == \
                                    QgsWKBTypes.GeometryCollection:
                        # Intersection produced different geomety types
                        temp_list = int_geom.asGeometryCollection()
                        for i in temp_list:
                            if i.type() == geom.type():
                                int_geom = QgsGeometry(i)
                                try:
                                    out_feature.setGeometry(int_geom)
                                    out_feature.setAttributes(atMapA + atMapB)
                                    writer.addFeature(out_feature)
                                except:
                                    LOGGER.debug(
                                        tr('Feature geometry error: One or '
                                           'more output features ignored due '
                                           'to invalid geometry.'))
                    else:
                        # Geometry list: prevents writing error
                        # in geometries of different types
                        # produced by the intersection
                        # fix #3549
                        if int_geom.wkbType() in wkb_type_groups[
                            wkb_type_groups[int_geom.wkbType()]]:
                            try:
                                out_feature.setGeometry(int_geom)
                                out_feature.setAttributes(atMapA + atMapB)
                                writer.addFeature(out_feature)
                            except:
                                LOGGER.debug(
                                    tr('Feature geometry error: One or more '
                                       'output features ignored due to '
                                       'invalid geometry.'))

            # the remaining bit of inFeatA's geometry
            # if there is nothing left, this will just silently fail and we
            # are good
            diff_geom = QgsGeometry(geom)
            if len(lstIntersectingB) != 0:
                intB = QgsGeometry.unaryUnion(lstIntersectingB)
                diff_geom = diff_geom.difference(intB)
                if diff_geom.isGeosEmpty() or not diff_geom.isGeosValid():
                    LOGGER.debug(
                        tr('GEOS geoprocessing error: One or more input '
                           'features have invalid geometry.'))

            if diff_geom.wkbType() == 0 or QgsWKBTypes.flatType(
                    diff_geom.geometry().wkbType()) == \
                    QgsWKBTypes.GeometryCollection:
                temp_list = diff_geom.asGeometryCollection()
                for i in temp_list:
                    if i.type() == geom.type():
                        diff_geom = QgsGeometry(i)
            try:
                out_feature.setGeometry(diff_geom)
                out_feature.setAttributes(atMapA)
                writer.addFeature(out_feature)
            except:
                LOGGER.debug(
                    tr('Feature geometry error: One or more output features '
                       'ignored due to invalid geometry.'))

    length = len(union_a.fields())
    atMapA = [None] * length

    # nFeat = len(union_b.getFeatures())
    for inFeatA in union_b.getFeatures():
        # progress.setPercentage(nElement / float(nFeat) * 100)
        add = False
        geom = inFeatA.geometry()
        diff_geom = QgsGeometry(geom)
        atMap = [None] * length
        atMap.extend(inFeatA.attributes())
        intersects = index_b.intersects(geom.boundingBox())

        if len(intersects) < 1:
            try:
                out_feature.setGeometry(geom)
                out_feature.setAttributes(atMap)
                writer.addFeature(out_feature)
            except:
                LOGGER.debug(
                    tr('Feature geometry error: One or more output features '
                       'ignored due to invalid geometry.'))
        else:
            request = QgsFeatureRequest().setFilterFids(intersects)

            # use prepared geometries for faster intersection tests
            engine = QgsGeometry.createGeometryEngine(diff_geom.geometry())
            engine.prepareGeometry()

            for inFeatB in union_a.getFeatures(request):
                atMapB = inFeatB.attributes()
                tmpGeom = inFeatB.geometry()

                if engine.intersects(tmpGeom.geometry()):
                    add = True
                    diff_geom = QgsGeometry(diff_geom.difference(tmpGeom))
                    if diff_geom.isGeosEmpty() or not diff_geom.isGeosValid():
                        LOGGER.debug(
                            tr('GEOS geoprocessing error: One or more input '
                               'features have invalid geometry.'))
                else:
                    try:
                        # Ihis only happends if the bounding box
                        # intersects, but the geometry doesn't
                        out_feature.setGeometry(diff_geom)
                        out_feature.setAttributes(atMap)
                        writer.addFeature(out_feature)
                    except:
                        LOGGER.debug(
                            tr('Feature geometry error: One or more output '
                               'features ignored due to invalid geometry.'))

        if add:
            try:
                out_feature.setGeometry(diff_geom)
                out_feature.setAttributes(atMap)
                writer.addFeature(out_feature)
            except:
                LOGGER.debug(
                    tr('Feature geometry error: One or more output features '
                       'ignored due to invalid geometry.'))
        nElement += 1

    # End of copy/paste fron processing

    writer.commitChanges()
    return writer