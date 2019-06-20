#!/usr/bin/env python

import boto3
from botocore.exceptions import ClientError
import botocore
import sys
import re
import os
import argparse
import configparser
import pprint
import hashlib
import datetime
import mimetypes

LOCAL_DIR   = os.path.dirname(os.path.realpath(__file__))
BASE_DIR    = os.path.dirname(LOCAL_DIR)
PACKAGE_DIR = BASE_DIR + "/packages" 
CONFIG_FILE = "s3_deploy.cfg"

CACHE_SECONDS  = 90 * 24 * 60 * 60
NO_CACHE_FILES = [ 'index.html', 'asset-manifest.json' ]

PROG_DESC = """Build a create-react-app production deployment and copy to S3.

"""

def usage (sMsg = None):
    """Print the usage information and exit"""
    if sMsg != None:
        printStdError("error: " + sMsg + "\n")
    oParser = getArgParser()
    oParser.print_help()
    sys.exit(-1)

def printStdError (sOutput):
    """Print to standard error"""
    sys.stderr.write(sOutput + "\n")

def errorMsg (sMsg, bExit = True):
    """Print an error message and optionally exit program"""
    printStdError("Error: " + sMsg)
    if bExit:
        sys.exit(-1)

def statusMsg (sMsg, bNewLine = False):
    if bNewLine:
        print("")
    print(" *** %s ***" % (sMsg))

def awsError (e):
    """Print an AWS exception message and exit"""
    errorMsg('AWS - {}.'.format(e.response['Error']['Message']))

def prettyPrint (sVal):
    """Better printing"""
    pprint.PrettyPrinter(indent=2).pprint(sVal)

def md5Checksum (filePath):
    with open(filePath, 'rb') as fh:
        m = hashlib.md5()
        while True:
            data = fh.read(8192)
            if not data:
                break
            m.update(data)
        return m.hexdigest()

def getArgParser ():
    """Management of the command-line argument parser"""
    oParser = argparse.ArgumentParser(description=PROG_DESC, formatter_class=argparse.RawTextHelpFormatter)
    oParser.add_argument('sProduct', help='product (required)', metavar='PRODUCT')
    oParser.add_argument('sDeployment', help='deployment (required)', metavar='DEPLOYMENT')
    oParser.add_argument('sBuildDir', help='build directory (required)', metavar='DIRECTORY')
    oParser.add_argument('-d', '--dry-run', action='store_true', dest='bDryRun',
                         help='run without transferring to S3')
    oParser.add_argument('-f', '--force-transfer', action='store_true', dest='bForceTransfer',
                         help='transfer all build files, ignoring existing files on S3')
    oParser.add_argument('-i', '--invalidation-only', action='store_true', dest='bInvalidCFOnly',
                         help='create invalidation for CloudFront only')
    oParser.add_argument('-m', '--maintain-versions', action='store', dest='iVersions', type=int,
                         help='number of versions to maintain', metavar='VERSIONS')
    return oParser

def searchList (sNeedle, aHaystack):
    """Get the index of element in a list or return false"""
    try:
        return aHaystack.index(sNeedle)
    except ValueError:
        return False

def getCwdFiles ():
    """Get a recursive file listing of the current directory"""
    aAllFiles = []
    for sRoot, aDirs, aFiles in os.walk('.'):
        for sFile in aFiles:
            sPath = re.sub(r'^\./', '', sRoot + '/' + sFile)
            aAllFiles.append(sPath)
    return aAllFiles

class Deploy:
    def main (self):
        """Primary class method"""
        self.getCmdOptions()
        self.getConfig()
        self.validateTarget()
        self.goToBuildDir()
        self.syncToS3()
        self.clearCloudFront()

    def validateTarget (self):
        """Validate the deployment target"""

        self.PRODUCTS    = self.getConfigValue('general', 'products').split()
        self.DEPLOYMENTS = self.getConfigValue('general', 'deployments').split()
        self.S3_BUCKET   = self.getConfigValue('general', 's3_bucket')
        
        if searchList(self.oCmdOptions.sProduct, self.PRODUCTS) is False:
            errorMsg("invalid product: %s, valid products are: %s" %
                     (self.oCmdOptions.sProduct, ", ".join(self.PRODUCTS)))
            
        if searchList(self.oCmdOptions.sDeployment, self.DEPLOYMENTS) is False:
            errorMsg("invalid deployment: %s, valid deployments are: %s" %
                     (self.oCmdOptions.sDeployment, ", ".join(self.DEPLOYMENTS)))

        self.CF_DIST_ID = self.getConfigValue('cloudfront-' + self.oCmdOptions.sProduct,
                                              self.oCmdOptions.sDeployment + '-dist-id')

        # Connect to S3 with the configured credentials and validate
        sId = os.environ.get('AWS_S3_DEPLOY_ACCESS_ID') or self.getConfigValue('aws-credentials', 'access_id') 
        sKey = os.environ.get('AWS_S3_DEPLOY_SECRET_KEY') or self.getConfigValue('aws-credentials', 'secret_key') 
        
        self.oBoto = boto3.client('s3', aws_access_key_id=sId, aws_secret_access_key=sKey)
        try:
            statusMsg("Validating AWS credentials")
            self.oBoto.list_objects_v2(Bucket=self.S3_BUCKET, MaxKeys=1)
        except ClientError as e:
            awsError(e)
        self.oBotoCF = boto3.client('cloudfront', aws_access_key_id=sId, aws_secret_access_key=sKey)
            

    def goToBuildDir (self):
        """Go to the build directory and validate files"""
        if not os.path.isdir(self.oCmdOptions.sBuildDir):
            errorMsg("Build directory does not exist: " + self.oCmdOptions.sBuildDir)

        os.chdir(self.oCmdOptions.sBuildDir)
        for sFile in NO_CACHE_FILES:
            if not os.path.isfile(sFile):
                errorMsg("Build directory is missing files: " + self.oCmdOptions.sBuildDir)

    def getCmdOptions (self):
        """Get all command line args as an object, stored in a static variable"""

        # Return the attribute if set, otherwise set 
        oParser = getArgParser()
        self.oCmdOptions = oParser.parse_args()

    def getConfigValue (self, sSection, sKey, bRequired = True):
        """Get a configuration value"""
        sValue = None
        if self.oConfig.has_section(sSection):
            if self.oConfig.has_option(sSection, sKey):
               sValue =  self.oConfig[sSection][sKey]
            elif bRequired:
                errorMsg("Missing configuration option: %s:%s" % (sSection, sKey))
        elif bRequired:
            errorMsg("Missing configuration section: " + sSection)
        return sValue

    def getConfig (self):
        """Get all configuration elements"""
        self.oConfig = configparser.RawConfigParser()
        self.oConfig.read(LOCAL_DIR + "/" +  CONFIG_FILE)

    def getS3Files (self, sBucket, sPrefix):
        """Get all files and sizes from S3"""
        oResponse = self.oBoto.list_objects_v2(Bucket = sBucket, Prefix = sPrefix)
        try:
            aContents = oResponse['Contents']
        except KeyError:
            return {}
        
        # Sort by last modified, newest on top
        get_last_modified = lambda obj: int(obj['LastModified'].strftime('%s'))
        aContents = [obj for obj in sorted(aContents, key=get_last_modified, reverse=True)]

        aFiles = {}
        for oContent in aContents:
            sKey = oContent['Key'].replace(sPrefix + '/', '')
            aFiles[sKey] = {
                'key':      sKey,
                'etag':     re.sub(r'^"(.*)"$', '\\1', oContent['ETag']),
                'size':     oContent['Size'],
                'modified': oContent['LastModified']
            }
        return aFiles

    def compareFiles (self, aBuildFiles, aS3FileInfo):
        """Get a list of new build files and old S3 files"""
        aS3Files     = aS3FileInfo.keys()
        setBuild     = set(aBuildFiles)
        setS3        = set(aS3Files)
        aNewFiles    = list(setBuild - setS3)
        aOldS3Files  = list(setS3 - setBuild)
        aCommonFiles = list(setBuild & setS3)

        # Compare comman files by their S3 etags (always MD5 in normal circumstances)
        for sFile in aCommonFiles:
            if self.oCmdOptions.bForceTransfer or aS3FileInfo[sFile]['etag'] != md5Checksum(sFile):
                aNewFiles.append(sFile)
                
            # Always add the manifest as new so the date is updated
            elif re.match('precache-manifest', sFile):
                aNewFiles.append(sFile) 
                
        return aNewFiles, aOldS3Files


    def removeS3Files (self, sBucket, sPrefix, aFiles):
        """Remove files from S3"""
        for sFile in aFiles:
            sKey = '%s/%s' % (sPrefix, sFile)
            print(" - removing s3://%s/%s" % (sBucket, sKey)) 
            if not self.oCmdOptions.bDryRun:
                self.oBoto.delete_object(Bucket=sBucket, Key=sKey)

        
    def transferFiles (self, sBucket, sPrefix, aFiles):
        """Transfer files to S3"""

        # Caching states
        sCacheAlways = 'max-age=%d, public' % (CACHE_SECONDS)
        sCacheNever  = 'max-age=0, no-cache, must-revalidate, proxy-revalidate, no-store'
        
        # Mapping file type - all others should be defined
        mimetypes.add_type('application/octet-stream', '.map')

        for sFile in aFiles:
            sKey = '%s/%s' % (sPrefix, sFile)
            sMime, sEncoding = mimetypes.guess_type(sFile)
            print(" - transfering to s3://%s/%s" % (sBucket, sKey))
            if not self.oCmdOptions.bDryRun:
                data = open(sFile, 'rb')
                if searchList(sFile, NO_CACHE_FILES) is False:
                    self.oBoto.put_object(Body=data, Bucket=sBucket, CacheControl=sCacheAlways,
                                          ContentType=sMime, Key=sKey)
                else:
                    self.oBoto.put_object(Body=data, Bucket=sBucket, CacheControl=sCacheNever,
                                          ContentType=sMime, Key=sKey)


    def maintainVersions (self, aS3FileInfo, aOldS3Files, iVersions, sBucket, sPrefix):
        """Maintain files from older versions"""

        # Get the old version files and sort by date
        aManifests = []
        for sKey, oFile in aS3FileInfo.items():
            if len(aManifests) >= iVersions:
                break
            if re.match('precache-manifest', sKey) and searchList(sKey, aOldS3Files) is not False:
                aManifests.append(oFile)

        # Get the content of each manifest and add the elements to exclusion array
        aExclude = []
        for oFile in aManifests:
            aExclude.append(oFile['key'])
            sKey = '%s/%s' % (sPrefix, oFile['key'])
            oResponse = self.oBoto.get_object(Bucket=sBucket, Key=sKey)
            for sUrl in re.findall(r'"url": "/(.*?)"', str(oResponse['Body'].read())):
                aExclude.append(sUrl)

        # Remove any of the excluded files from the old list
        return list(set(aOldS3Files) - set(aExclude))
            

    def syncToS3 (self):
        """Sync all files to S3 - assume we are in the build directory"""

        if self.oCmdOptions.bInvalidCFOnly:
            return
        
        # Get all the build files
        aBuildFiles = getCwdFiles()
        # prettyPrint(aBuildFiles)

        # Get all files and sizes from S3
        sPrefix = 'deployments/%s/%s' % (self.oCmdOptions.sProduct, self.oCmdOptions.sDeployment)
        aS3FileInfo = self.getS3Files(self.S3_BUCKET, sPrefix)
        # prettyPrint(aS3FileInfo)

        # Get the list of new build files and old S3 files
        aNewBuildFiles, aOldS3Files = self.compareFiles(aBuildFiles, aS3FileInfo)
        # prettyPrint(aNewBuildFiles)
        # prettyPrint(aOldS3Files)

        # Avoid removing files that are part of older versions
        if self.oCmdOptions.iVersions and int(self.oCmdOptions.iVersions) > 0:
            aOldS3Files = self.maintainVersions(aS3FileInfo, aOldS3Files, self.oCmdOptions.iVersions,
                                                self.S3_BUCKET, sPrefix)

        # Transfer the new files
        self.transferFiles(self.S3_BUCKET, sPrefix, aNewBuildFiles)

        # Remove any old files
        self.removeS3Files(self.S3_BUCKET, sPrefix, aOldS3Files)

    def clearCloudFront (self):
        """Send a complete invalidation to the CloudFront distribution"""
        if self.oCmdOptions.bDryRun:
            return
                
        statusMsg("Clearing CloudFront distribution: " + self.CF_DIST_ID, True)
        self.oBotoCF.create_invalidation(DistributionId=self.CF_DIST_ID,
                                         InvalidationBatch={
                                             'Paths': { 'Quantity': 1, 'Items': [ '/*' ] },
                                             'CallerReference': 's3-deploy-{}'.format(datetime.datetime.now())
                                         })

# Run the system
oDeploy = Deploy()
oDeploy.main()
