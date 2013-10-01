# -*- coding: utf-8 -*-
"""
/***************************************************************************
 Qadastre - import main methods
                                 A QGIS plugin
 This plugins helps users to import the french land registry ('cadastre')
 into a database. It is meant to ease the use of the data in QGIs
 by providing search tools and appropriate layer symbology.
                              -------------------
        begin                : 2013-06-11
        copyright            : (C) 2013 by 3liz
        email                : info@3liz.com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import sys, os, glob
import re
import time
import tempfile
import shutil
from distutils import dir_util
from PyQt4.QtCore import *
from PyQt4.QtGui import *
from qgis.core import *
from datetime import datetime

# db_manager scripts
from db_manager.db_plugins.plugin import DBPlugin, Schema, Table, BaseError
from db_manager.db_plugins import createDbPlugin
from db_manager.dlg_db_error import DlgDbError




class qadastreImport(QObject):

    def __init__(self, dialog):
        self.dialog = dialog

        # common qadastre methods
        self.qc = self.dialog.qc

        self.db = self.dialog.db
        self.connector = self.db.connector
        self.scriptSourceDir = os.path.join(self.qc.plugin_dir, "scripts/opencadastre/trunk/data/pgsql")

        # create temporary directories
        s = QSettings()
        tempDir = s.value("qadastre/tempDir", '%s' % tempfile.gettempdir(), type=str)
        self.scriptDir = tempfile.mkdtemp('', 'qad', tempDir)
        self.edigeoDir = tempfile.mkdtemp('', 'qad', tempDir)
        self.edigeoPlainDir = tempfile.mkdtemp('', 'qad', tempDir)
        self.majicDir = tempfile.mkdtemp('', 'qad', tempDir)
        self.replaceDict = {
            '[VERSION]': self.dialog.dataVersion,
            '[ANNEE]': self.dialog.dataYear
        }
        if self.dialog.dbType == 'postgis':
            self.replaceDict['[PREFIXE]'] = '"%s".' % self.dialog.schema
        else:
            self.replaceDict['[PREFIXE]'] = ''
        self.go = True
        self.startTime = datetime.now()
        self.step = 0
        self.totalSteps = 0

        self.beginImport()


    def beginJobLog(self, stepNumber, title):
        '''
        reinit progress bar
        '''
        self.totalSteps = stepNumber
        self.step = 0
        self.dialog.stepLabel.setText('<b>%s</b>' % title)
        self.qc.updateLog('<h3>%s</h3>' % title)


    def updateProgressBar(self):
        '''
        Update the progress bar
        '''
        if self.go:
            self.step+=1
            self.dialog.pbProcess.setValue(int(self.step * 100/self.totalSteps))


    def updateTimer(self):
        '''
        Update the timer for each process
        '''
        if self.go:
            b = datetime.now()
            diff = b - self.startTime
            self.qc.updateLog(u'%s s' % diff.seconds)


    def beginImport(self):
        '''
        Process to run before importing data
        '''

        # Log
        jobTitle = u'INITIALISATION'
        self.beginJobLog(2, jobTitle)

        # Set postgresql synchronous_commit to off
        # to speed up bulk inserts
        if self.dialog.dbType == 'postgis':
            sql = "SET LOCAL synchronous_commit TO off;"

        if self.dialog.dbType == 'spatialite':
            sql = 'PRAGMA synchronous = OFF;PRAGMA journal_mode = MEMORY;PRAGMA temp_store = MEMORY;PRAGMA cache_size = 500000'

        self.executeSqlQuery(sql)

        # copy opencadastre script files to temporary dir
        self.updateProgressBar()
        self.copyFilesToTemp(self.scriptSourceDir, self.scriptDir)
        self.updateTimer()
        self.updateProgressBar()


    def installOpencadastreStructure(self):
        '''
        Create the empty db structure
        '''

        # Log
        jobTitle = u'STRUCTURATION BDD'
        self.beginJobLog(6, jobTitle)

        # install opencadastre structure
        scriptList = [
            {'title' : u'Création des tables',
                'script': '%s' % os.path.join(self.scriptDir, 'create_metier.sql')},
            {'title': u'Création des tables edigeo',
                'script': '%s' % os.path.join(self.qc.plugin_dir, 'scripts/edigeo_create_import_tables.sql')},
            #~ {'title' : u'Ajout des contraintes',
                #~ 'script': '%s' % os.path.join(self.scriptDir, 'create_constraints.sql')},
            {'title' : u'Ajout de la nomenclature',
                'script': '%s' % os.path.join(self.scriptDir, 'insert_nomenclatures.sql')}
        ]

        for item in scriptList:
            s = item['script']
            self.dialog.subStepLabel.setText(item['title'])
            self.qc.updateLog('%s' % item['title'])
            self.updateProgressBar()
            self.executeSqlScript(s)
            self.updateProgressBar()

        self.updateTimer()


    def importMajic(self):

        # Log
        jobTitle = u'MAJIC'
        self.beginJobLog(14, jobTitle)

        # copy files in temp dir
        self.dialog.subStepLabel.setText('Copie des fichiers')
        self.updateProgressBar()
        self.copyFilesToTemp(self.dialog.majicSourceDir, self.majicDir)
        self.updateTimer()
        self.updateProgressBar()

        # replace parameters
        replaceDict = self.replaceDict.copy()
        for item in self.dialog.majicSourceFileNames:
            replaceDict[item['key']] = item['value']

            # create file if not there
            fpath = os.path.join(os.path.realpath(self.majicDir) + '/' , item['value'])
            if not os.path.exists(fpath):
                # create empty file
                fout = open(fpath, 'w')
                data = ''
                fout.write(data)
                fout.close()

        replaceDict['[CHEMIN]'] = os.path.realpath(self.majicDir) + '/'

        scriptList = []
        #~ scriptList.append(
            #~ {
            #~ 'title' : u'Suppression des contraintes',
            #~ 'script' : 'COMMUN/suppression_constraintes.sql'
            #~ }
        #~ )
        scriptList.append(
            {
            'title' : u'Purge des données',
            'script' : 'COMMUN/majic3_purge_donnees.sql'
            }
        )
        if self.dialog.dbType == 'postgis':
            importScript = {
                'title' : u'Import des fichiers majic',
                'script' : 'COMMUN/majic3_import_donnees_brutes.sql'
            }
        if self.dialog.dbType == 'spatialite':
            importScript = {
                'title' : u'Import des fichiers majic',
                'method' : self.importMajicIntoSpatialite
            }
        scriptList.append(importScript)
        scriptList.append(
            {
            'title' : u'Mise en forme des données',
            'script' : '%s/majic3_formatage_donnees.sql' % self.dialog.dataVersion
            }
        )
        scriptList.append(
            {
            'title' : u'Purge des données brutes',
            'script' : 'COMMUN/majic3_purge_donnees_brutes.sql'
            }
        )

        for item in scriptList:
            self.dialog.subStepLabel.setText(item['title'])
            self.qc.updateLog('%s' % item['title'])
            if item.has_key('script'):
                s = item['script']
                scriptPath = os.path.join(self.scriptDir, s)
                self.replaceParametersInScript(scriptPath, replaceDict)
                self.updateProgressBar()
                self.executeSqlScript(scriptPath)
            else:
                self.updateProgressBar()
                item['method']()
            self.updateTimer()
            self.updateProgressBar()

        return None


    def chunks(self, data, rows=50000):
        '''
        Divides the data into 50000 rows each
        '''
        for i in xrange(0, len(data), rows):
            yield data[i:i+rows]

    def importMajicIntoSpatialite(self):
        '''
        Method wich read each majic file
        and bulk import data intp temp tables
        - Specific for sqlite cause to COPY statement
        '''
        # Loop through all majic files
        for item in self.dialog.majicSourceFileNames:
            fpath = os.path.join(os.path.realpath(self.majicDir) + '/' , item['value'])
            table = item['table']
            # read file content
            lines = None
            with open(fpath) as fin:
                lines = fin.read().splitlines()
            if lines:
                divLines = self.chunks(lines)
                for a in divLines:
                    c = self.connector._get_cursor()
                    c.executemany('insert into %s values (?)' % table, [(x,) for x in a] )
                    self.connector._commit()


    def importEdigeo(self):

        try:
            from osgeo import gdal, ogr, osr
            gdalAvailable = True
        except:
            msg = u"Erreur : la librairie GDAL n'est pas accessible"
            self.go = False
            return msg

        # Log
        jobTitle = u'EDIGEO'
        self.beginJobLog(14, jobTitle)
        self.qc.updateLog(u'Type de base : %s, Connexion: %s, Schéma: %s' % (
                self.dialog.dbType,
                self.dialog.connectionName,
                self.dialog.schema
            )
        )
        self.updateProgressBar()


        # copy files in temp dir
        self.dialog.subStepLabel.setText('Copie des fichiers')
        self.updateProgressBar()
        self.copyFilesToTemp(self.dialog.edigeoSourceDir, self.edigeoDir)
        self.updateTimer()
        self.updateProgressBar()

        # unzip edigeo files in temp dir
        self.dialog.subStepLabel.setText('Extraction des fichiers')
        self.updateProgressBar()
        self.unzipFolderContent(self.edigeoDir)
        self.updateTimer()
        self.updateProgressBar()

        # import edigeo thf files into database
        self.dialog.subStepLabel.setText('Import des fichiers')
        self.updateProgressBar()
        self.importAllEdigeoToDatabase()
        self.updateTimer()
        self.updateProgressBar()

        # Format edigeo data
        replaceDict = self.replaceDict.copy()
        replaceDict['[DEPDIR]'] = '%s%s' % (self.dialog.edigeoDepartement, self.dialog.edigeoDirection)
        replaceDict['[LOT]'] = self.dialog.edigeoLot
        scriptList = [
            {
                'title' : u'Mise en forme des données',
                'script' : '%s' % os.path.join(
                    self.scriptDir,
                    '%s/edigeo_formatage_donnees.sql' % self.dialog.dataVersion
                )
            },
            #~ {   'title' : u'Création Unités foncières',
                #~ 'script' : '%s' % os.path.join(
                    #~ self.scriptDir,
                    #~ '%s/edigeo_unite_fonciere.sql' % self.dialog.dataVersion
                #~ )
            #~ },
            {
                'title' : u'Placement des étiquettes',
                'script' : '%s/edigeo_add_labels_xy.sql' % os.path.join(
                    self.qc.plugin_dir,
                    "scripts/"
                )
            },
            {
                'title' : u'Création des indexes spatiaux',
                'script' : '%s/edigeo_create_indexes.sql' % os.path.join(
                    self.qc.plugin_dir,
                    "scripts/"
                )
            }
        ]
        for item in scriptList:
            if self.go:
                self.dialog.subStepLabel.setText(item['title'])
                self.qc.updateLog('%s' % item['title'])
                scriptPath = item['script']
                self.replaceParametersInScript(scriptPath, replaceDict)
                self.updateProgressBar()
                self.executeSqlScript(scriptPath)
                self.updateTimer()
                self.updateProgressBar()


        # drop edigeo raw data
        self.dialog.subStepLabel.setText('Suppression des fichiers temporaires')
        self.dropEdigeoRawData()
        self.updateTimer()
        self.updateProgressBar()

        return None





    def endImport(self):
        '''
        Actions done when import has finished
        '''
        # Log
        jobTitle = u'FINALISATION'
        self.beginJobLog(1, jobTitle)

        # Re-set SQL optimization parameters to default
        if self.dialog.dbType == 'postgis':
            sql = "SET LOCAL synchronous_commit TO on;"
            self.executeSqlQuery(sql)

        # Remove the temp folders
        self.dialog.subStepLabel.setText(u'Suppression des données temporaires')
        self.updateProgressBar()
        tempFolderList = [
            self.scriptDir,
            self.edigeoDir,
            self.edigeoPlainDir,
            self.majicDir
        ]
        try:
            for rep in tempFolderList:
                if os.path.exists(rep):
                    shutil.rmtree(rep)
        except IOError, e:
            msg = u"Erreur lors de la suppresion des répertoires temporaires: %s" % e
            self.go = False
            return msg

        if self.go:
            msg = u"Import terminé"
        else:
            msg = u"Des erreurs ont été rencontrées pendant l'import. Veuillez consulter le log."

        self.updateProgressBar()
        self.updateTimer()
        QMessageBox.information(self.dialog, "Qadastre", msg)
        return None

    #
    # TOOLS
    #


    def copyFilesToTemp(self, source, target):
        '''
        Copy opencadastre scripts
        into a temporary folder
        '''
        if self.go:

            self.qc.updateLog(u'* Copie du répertoire %s' % source.decode('UTF8'))

            QApplication.setOverrideCursor(Qt.WaitCursor)

            # copy script directory
            try:
                dir_util.copy_tree(source, target)
                os.chmod(target, 0777)
            except IOError, e:
                msg = u"Erreur lors de la copie des scripts d'import: %s" % e
                QMessageBox.information(self.dialog,
                "Qadastre", msg)
                self.go = False
                return msg

            finally:
                QApplication.restoreOverrideCursor()


        return None


    def listFilesInDirectory(self, path, ext=None):
        '''
        List all files from folder and subfolder
        for a specific extension if given
        '''
        fileList = []
        for root, dirs, files in os.walk(path):
            for i in files:
                if not ext or (ext and os.path.splitext(i)[1][1:].lower() == ext):
                    fileList.append(os.path.join(root, i))
        return fileList


    def unzipFolderContent(self, path):
        '''
        Scan content of specified path
        and unzip all content into a single folder
        '''
        if self.go:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self.qc.updateLog(u'* Décompression des fichiers de %s' % path.decode('UTF8'))

            # get all the zip files
            zipFileList = self.listFilesInDirectory(path, 'zip')
            tarFileList = self.listFilesInDirectory(path, 'bz2')

            # unzip all files
            import zipfile
            import tarfile
            try:
                for z in zipFileList:
                    zipfile.ZipFile(z).extractall(self.edigeoPlainDir)

                inner_zips_pattern = os.path.join(self.edigeoPlainDir, "*.zip")
                i=0
                for filename in glob.glob(inner_zips_pattern):
                    inner_folder = filename[:-4] + '_%s' % i
                    zipfile.ZipFile(filename).extractall(inner_folder)
                    i+=1
                i=0
                for z in tarFileList:
                    with tarfile.open(z) as t:
                        tar = t.extractall(os.path.join(self.edigeoPlainDir, '_%s' % i))
                        i+=1
                        t.close()

            except IOError, e:
                msg = u"Erreur lors de l'extraction des fichiers EDIGEO: %s" % e
                self.go = False
                self.qc.updateLog(msg)
                return msg

            finally:
                QApplication.restoreOverrideCursor()


    def replaceParametersInString(self, string, replaceDict):
        '''
        Replace all occurences in string
        '''

        def replfunc(match):
            return replaceDict[match.group(0)]

        regex = re.compile('|'.join(re.escape(x) for x in replaceDict), re.IGNORECASE)
        string = regex.sub(replfunc, string)
        return string


    def replaceParametersInScript(self, scriptPath, replaceDict):
        '''
        Replace all parameters in sql scripts
        with given values
        '''

        if self.go:

            QApplication.setOverrideCursor(Qt.WaitCursor)

            try:
                fin = open(scriptPath)
                data = fin.read().decode("utf-8-sig")
                fin.close()
                fout = open(scriptPath, 'w')
                data = self.replaceParametersInString(data, replaceDict)
                data = data.encode('utf-8')
                fout.write(data)
                fout.close()

            except IOError, e:
                msg = u"Erreur lors du paramétrage des scripts d'import: %s" % e
                self.go = False
                self.qc.updateLog(msg)
                return msg

            finally:
                QApplication.restoreOverrideCursor()


        return None


    def executeSqlScript(self, scriptPath):
        '''
        Execute an SQL script file
        from opencadastre
        '''

        if self.go:

            QApplication.setOverrideCursor(Qt.WaitCursor)

            # Read sql script
            sql = open(scriptPath).read()
            sql = sql.decode("utf-8-sig")

            # Set schema if needed
            if self.dialog.dbType == 'postgis':
                sql = self.qc.setSearchPath(sql, self.dialog.schema)
            # Execute query
            self.executeSqlQuery(sql)


        return None


    def postgisToSpatialite(self, sql):
        '''
        Convert postgis SQL statement
        into spatialite compatible
        statements
        '''

        # delete some incompatible options
        # replace other by spatialite syntax
        replaceDict = [
            # delete
            {'in': r'with\(oids=.+\)', 'out': ''},
            {'in': r'comment on [^;]+;', 'out': ''},
            {'in': r'alter table [^;]+add primary key[^;]+;', 'out': ''},
            {'in': r'alter table [^;]+drop column[^;]+;', 'out': ''},
            {'in': r'analyse [^;]+;', 'out': ''},
            # replace
            {'in': r'distinct on *\([a-z, ]+\)', 'out': 'distinct'},
            {'in': r'serial', 'out': 'INTEGER PRIMARY KEY AUTOINCREMENT'},
            {'in': r'current_schema::text, ', 'out': ''},
            {'in': r'substring', 'out': 'SUBSTR'},
            {'in': r"(to_char\()([^']+) *, *'[09]+' *\)", 'out': r"CAST(\2 AS TEXT)"},
            {'in': r"(to_number\()([^']+) *, *'[09]+' *\)", 'out': r"CAST(\2 AS integer)"},
            {'in': r"(to_date\()([^']+) *, *'DDMMYYYY' *\)", 'out': r"strftime('%d%m%Y',\2)"},
            {'in': r"(to_date\()([^']+) *, *'DD/MM/YYYY' *\)", 'out': r"strftime('%d/%m/%Y',\2)"},
            {'in': r"(to_date\()([^']+) *, *'YYYYMMDD' *\)", 'out': r"strftime('%Y%m%d',\2)"},
        ]


        for a in replaceDict:
            r = re.compile(a['in'], re.IGNORECASE|re.MULTILINE)
            sql = r.sub(a['out'], sql)

        # index spatiaux
        r = re.compile(r'(create index [^;]+ ON )([^;]+)( USING +)(gist +)?\(([^;]+)\);',  re.IGNORECASE|re.MULTILINE)
        sql = r.sub(r'SELECT createSpatialIndex("\2", "\5");', sql)

        # replace postgresql "update from" statement
        r = re.compile(r'(update [^;=]+)(=)([^;=]+ FROM [^;]+)(;)', re.IGNORECASE|re.MULTILINE)
        sql = r.sub(r'\1=(SELECT \3);', sql)

        # replace multiple column update for geo_parcelle
        r = re.compile(r'update [^;]+parcelle, dvoilib, comptecommunal[^;]+;',  re.IGNORECASE|re.MULTILINE)
        res = r.findall(sql)
        replaceBy = ''
        for statement in res:
            for a in ['parcelle', 'dvoilib', 'comptecommunal']:
                st = statement
                st = st.replace('(parcelle, dvoilib, comptecommunal)', '%s' % a)
                st = st.replace('(p.parcelle, p.dvoilib, p.comptecommunal)', '(SELECT p.%s' % a)
                st = st.replace(';', ');')
                replaceBy+= st
            sql = sql.replace(statement, replaceBy)


        # majic formatage : replace multiple column update for geo_parcelle
        r = re.compile(r'update local10 set[^;]+;',  re.IGNORECASE|re.MULTILINE)
        res = r.findall(sql)
        replaceBy = ''
        for statement in res:
            replaceBy = '''
            UPDATE local10 SET
              ccopre = $ local00.ccopre @,
              ccosec = $ local00.ccosec @,
              dnupla = $ local00.dnupla @,
              ccoriv = $ local00.ccoriv @,
              ccovoi = $ local00.ccovoi @,
              dnvoiri = $ local00.dnvoiri @,
              local00 = $ local10.annee||local10.invar @,
              parcelle = $ REPLACE(local10.annee||local10.ccodep||local10.ccodir||local10.ccocom||local00.ccopre||local00.ccosec||local00.dnupla,' ', '-') @,
              voie= $  REPLACE(local10.annee||local10.ccodep||local10.ccodir||local10.ccocom||local00.ccovoi,' ', '-') @
            WHERE local10.annee='%s';
            ''' % self.dialog.dataYear
            replaceBy = replaceBy.replace('$', '(SELECT ')
            replaceBy = replaceBy.replace('@', " FROM local00 WHERE local00.invar = local10.invar AND local00.annee='%s' AND local10.annee='%s')" % (self.dialog.dataYear, self.dialog.dataYear))
            sql = sql.replace(statement, replaceBy)

        return sql

    def executeSqlQuery(self, sql):
        '''
        Execute a SQL string query
        And commit
        '''
        if self.go:
            if self.dialog.dbType == 'spatialite':
                # compatibility issues
                sql = self.postgisToSpatialite(sql)
            if sql:
                self.qc.updateLog('|%s|' % sql)
                c = None
                try:
                    if self.dialog.dbType == 'postgis':
                        c = self.connector._execute(sql)
                    if self.dialog.dbType == 'spatialite':
                        c = self.connector._get_cursor()
                        c.executescript(sql)

                except BaseError as e:
                    DlgDbError.showError(e, self.dialog)
                    self.go = False
                    self.qc.updateLog(e.msg)
                    return

                finally:
                    QApplication.restoreOverrideCursor()
                    if c:
                        c.close()
                        del c


    def importAllEdigeoToDatabase(self):
        '''
        Loop through all THF files
        and import each one into database
        '''

        if self.go:

            self.qc.updateLog(u'* Import des fichiers EDIGEO dans la base')

            initialStep = self.step
            initialTotalSteps = self.totalSteps

            # THF
            self.dialog.subStepLabel.setText(u'Import des fichiers via ogr2ogr')
            self.qc.updateLog(u'  - Import des fichiers via ogr2ogr')
            thfList = self.listFilesInDirectory(self.edigeoPlainDir, 'thf')
            self.step = 0
            self.totalSteps = len(thfList)
            for thf in thfList:
                self.importEdigeoThfToDatabase(thf)
                self.updateProgressBar()

            # VEC - import relations between objects
            self.dialog.subStepLabel.setText(u'Import des relations (*.vec)')
            self.qc.updateLog(u'  - Import des relations (*.vec)')
            vecList = self.listFilesInDirectory(self.edigeoPlainDir, 'vec')
            self.step = 0
            self.totalSteps = len(vecList)
            for vec in vecList:
                self.importEdigeoVecToDatabase(vec)
                self.updateProgressBar()

            # Reinit progress var
            self.step = initialStep
            self.totalSteps = initialTotalSteps
            QApplication.restoreOverrideCursor()


    def importEdigeoThfToDatabase(self, filename):
        '''
        Import one edigeo THF files into database
        source : db_manager/dlg_import_vector.py
        '''
        if self.go:
            # Get options
            sourceSrid = self.dialog.edigeoSourceProj
            targetSrid = self.dialog.edigeoTargetProj
            targetSridOption = '-t_srs'
            if sourceSrid == targetSrid:
                targetSridOption = '-a_srs'

            # Build ogr2ogr command
            conn_name = self.dialog.connectionName
            settings = QSettings()
            settings.beginGroup( u"/%s/%s" % (self.db.dbplugin().connectionSettingsKey(), conn_name) )
            if self.dialog.dbType == 'postgis':
                if not settings.contains( "database" ): # non-existent entry?
                    raise InvalidDataException( self.tr('There is no defined database connection "%s".') % conn_name )
                settingsList = ["service", "host", "port", "database", "username", "password"]
                service, host, port, database, username, password = map(lambda x: settings.value(x), settingsList)

                ogrCommand = 'ogr2ogr -s_srs "%s" %s "%s" -append -f "PostgreSQL" PG:"host=%s port=%s dbname=%s active_schema=%s user=%s password=%s" %s -lco GEOMETRY_NAME=geom -lco PG_USE_COPY=YES -nlt GEOMETRY -gt 50000 --config OGR_EDIGEO_CREATE_LABEL_LAYERS NO' % (sourceSrid, targetSridOption, targetSrid, host, port, database, self.dialog.schema, username, password, filename)

            if self.dialog.dbType == 'spatialite':
                if not settings.contains( "sqlitepath" ): # non-existent entry?
                    raise InvalidDataException( u'there is no defined database connection "%s".' % conn_name )

                database = settings.value("sqlitepath")

                ogrCommand = 'ogr2ogr -s_srs "%s" %s "%s" -append -f "SQLite" "%s" %s -lco GEOMETRY_NAME=geom -nlt GEOMETRY  -dsco SPATIALITE=YES -gt 50000 --config OGR_EDIGEO_CREATE_LABEL_LAYERS NO --config OGR_SQLITE_SYNCHRONOUS OFF --config OGR_SQLITE_CACHE 512' % (sourceSrid, targetSridOption, targetSrid, database, filename)
            #~ self.qc.updateLog(ogrCommand)

            # Run command
            proc = QProcess()
            proc.start(ogrCommand)
            proc.waitForFinished()

        return None



    def importEdigeoVecToDatabase(self, path):
        '''
        Get edigeo relations between objects
        from a .VEC file
        and add them in edigeo_rel table
        '''
        if self.go:
            reg = '^RID[a-zA-z]{1}[a-zA-z]{1}[0-9]{2}:(Rel_.+)_(Objet_[0-9]+)_(Objet_[0-9]+)'
            with open(path) as inputFile:
                # Get a list of RID relations combining a "Rel" and two "_Objet"
                l = [ a[0] for a in [re.findall(r'%s' % reg, line) for line in inputFile] if a]

                # Create a sql script to insert all items
                sql="BEGIN;"
                for item in l:
                    sql+= "INSERT INTO edigeo_rel ( nom, de, vers) values ( '%s', '%s', '%s');" % (item[0], item[1], item[2] )
                sql+="COMMIT;"

                # Execute query
                if self.dialog.dbType == 'postgis':
                    sql = self.qc.setSearchPath(sql, self.dialog.schema)
                self.executeSqlQuery(sql)


    def dropEdigeoRawData(self):
        '''
        Drop Edigeo raw data tables
        '''

        if self.go:
            # DROP edigeo import tables
            edigeoTables = [
                'batiment_id',
                'borne_id',
                'boulon_id',
                'commune_id',
                'croix_id',
                'lieu_id'
                'numvoie_id',
                'parcelle_id',
                'ptcanv_id',
                'section_id',
                'subdfisc_id',
                'subdsect_id',
                'symblim_id',
                'tline_id',
                'tpoint_id_'
                'tronfluv_id'
                'tronroute_id',
                'tsurf_id',
                'voiep_id',
                'zoncommuni_id',
                'id_s_obj_z_1_2_2',
                'edigeo_rel',
            ]
            sql = ''
            for table in edigeoTables:
                sql+= 'DROP TABLE IF EXISTS "%s";' % table
            if self.dialog.dbType == 'postgis':
                sql = self.qc.setSearchPath(sql, self.dialog.schema)
            self.executeSqlQuery(sql)

