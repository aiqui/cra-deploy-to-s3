# Purpose

This application manages a deployment of a React application built Create React App (CRA), syncing the files to
an AWS S3 bucket.  It can manage the deployment of multiple projects to the same S3 bucket.  It maintains
older build files to prevent browser issues when trying to load older CRA build "chunks".

# Why deploy React to S3 / CloudFront 

React applications fit well with the S3 and CloudFront infrastructure.  The advantages:
* S3/CloudFront is fast, "serverless" and relatively inexpensive
* Through the CloudFront global endpoints (edge locations), an application can run quickly with high reliability
* CloudFront can manage multiple origins, including dynamic API
* CloudFront acts as a reverse proxy, eliminating cross-region (CORS) issues and greatly 
accelerating API calls in distant locations
* Using CloudFront origin paths, multiple deployments can be uploaded to a single S3 bucket

Some disadvantages could be:
* CloudFront creates another layer that would not be there when using a simple HTTP server,
and any configuration changes to the CDN are delayed
* Like any CDN, CloudFront caches content at the endpoints, so caching must be managed
* CloudFront endpoints are all over the world, so logging is not centralized like it would be for a single web server 
(CloudFront logging can be centralized - see [this repo][1])

# How this tool works

## S3 bucket structure

This tool assumes a structure of one S3 bucket with many CloudFront deployments.  The
bucket can contain many different "products", with each product containing multiple deployments.  
The S3 bucket will have a structure like this:

```
s3://my-s3-bucket/my-first-project/production
s3://my-s3-bucket/my-first-project/testing
s3://my-s3-bucket/my-second-project/production
s3://my-s3-bucket/my-second-project/testing
```

## Tool steps

This tool will 
1. Upload any new files to S3, validating the files via Etag to MD5
2. Delete any old files 
3. Optionally maintain old files that were part of earlier builds (downloading and parsing 
older `precache-manifest` files to determine which files are needed)
4. Set the HTTP cache parameters for different files (i.e. cache files with hash keys, no cache for common files)
5. Clear the CloudFront distribution (i.e. invalidation request)

# How to use

## Configuration
0. Install via `pip3.7 install git+https://github.com/aiqui/cra-deploy-to-s3.git`
1. Copy `s3_deploy.cfg.template` to `s3_deploy.cfg` and add your configuration elements
   - **Note**: *You may have only one "product" and "deployment" to start*
3. Add a CloudFront distribution for each product and deployment
4. Add the AWS credentials that have permissions to add and remove S3 files for the configured bucket, and can create CloudFront invalidations
5. python3 -m s3_deploy <options>

## Requirements
* Python 3.6 or above installed along with boto3 and other standard libraries
* Access to AWS S3 and CloudFront
* A production build of ReactJS

## Run the program

First you'll need to build your react application.  To transfer all the files to S3:
```
./s3_deploy.py <product> <deployment> <production-build-directory>
```

## Basic Concepts

There are a number of concepts to keep in mind when deploying a Create React App to S3/CloudFront:

* **CloudFront front end** - for a custom domain, SSL traffic will go through 
CloudFront and not S3 (which does not permit SSL with a custom domain)
* **One to many** - a single S3 bucket can hold many deployments (e.g. testing, production). 
You can set up each deployment with a dedicated CloudFront distribution pointing to the same bucket 
but a different prefix (e.g. deployments/testing, deployments/production)
* **Cross-domain API issues can be avoided** - there is a way to use CloudFront for both static files in 
S3 and a dynamic API, all in the same domain (see below)
* **Compression** - compression should always be enabled on CloudFront
* **Browser caching** - CRA build will create chunk files with hash keys.  These can be cached in the 
browser for long periods.  But files without hash keys like `index.html` should be set for no-caching.  
These caching attributes can set through S3.

## CloudFront React S3 Origin

Each CloudFront distribution can have multiple origins.  One origin will be set to S3 for the React 
build files.  

To add a new S3 origin to CloudFront:
1. Go to AWS CloudFront dashboard
2. Edit your instance
3. Go to Origins and Groups tab
4. Create an origin
5. Select the S3 bucket
6. Add the origin path, e.g. */my-first-project/production*

To add the React path:
1. Go the CloudFront instance, and the Behaviors tab
2. Click on Create Behavior
3. Select the S3 Origin
4. Disable Forward Cookies (it's going to static files)
5. Disable Query String Forwarding (again, static files)
6. Enable Compress Objects
7. Save

## Adding an API Server

Other CloudFront origins can be set up as well, including to an an API server.  If the API server 
is within your Virtual Private Cloud (VPC), CloudFront can safely use non-SSL (port 80) to communicate 
as a proxy server.  Not that the hostname that is passed to your API server will be the hostname of CloudFront instance 
*not* the API server hostname (e.g. `my.react-app.com` not `my.api.com`) because the HTTP request Host value is 
not modified (as normal for a proxy server)

To add an API server to CloudFront:

1. Similar to the steps above, add your API server as an origin, using only HTTP (insecure traffic) if within your VPC
2. Add a new CloudFront behavior, `/api/*` path pattern, HTTPS only viewer policy, all HTTP methods 
(unless you have GET only), `ALL` for **Cache Based on Selected Request Headers**, 
Compress Objects enabled, and **Forward All** for the query strings
3. Nothing should be cached by CloudFront (unless you can get away with this)

## How to enable the React Router in CloudFront

To enable different paths in React Router, [set the the CloudFront error page][2] to be `/index.html` (so that all failed requests will go there):

1. Go to CloudFront distributions in the AWS console 
2. Click on the appropriate CloudFront distribution 
3. Click on Error Pages tab
4. Add error responses for `403: Forbidden`, `404: Not Found` and `405: Method Not Allowed` pointing
    `/index.html` with HTTP response of `200`
5. The 403 and 404 will allow requests that fail to go through ReactJS
6. The 405 error will appear if there is a POST request to S3.  To prevent the S3 error from appearing, again the
failed request is passed through ReactJS

# Testing

## Testing HTTP headers

You can view this HTTP header if your S3 bucket is set for static website hosting (note S3 website hosting is not required for CloudFront to work):

```curl -I http://MY-S3-ENDPOINT/index.html```

Likewise you can test the header from CloudFront:

```curl -I https://CLOUDFRONT-URL/index.html```

To test compression, add encoding acceptance to the request HTTP header, e.g.

```curl -H "Accept-Encoding: gzip" -I https://CLOUDFRONT-URL/index.html```

  [1]: https://github.com/aiqui/cloudfront-log-consolidator 
  [2]: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/custom-error-pages.html

