# Why deploy React to S3 / CloudFront 

React applications on S3/CloudFront can be incredibly fast, "serverless" and very inexpensive.  Through the CloudFront global endpoints (edge locations), an application can run very quickly with high reliability.  By setting another source origin, CloudFront can act as a reverse proxy to an API, eliminating cross-region (CORS) issues and accelerating API calls in distant locations.  Multiple deployments can be uploaded to a single S3 bucket.


# How this tool works

This tool assumes a structure of one S3 bucket with many CloudFront deployments.  That bucket can contain many different "products", with each product containing multiple deployments.  That single S3 bucket will have a structure like this:

```
s3://my-s3-bucket//my-first-project/production
s3://my-s3-bucket//my-first-project/testing
s3://my-s3-bucket//my-second-project/production
s3://my-s3-bucket//my-second-project/testing
```

This tool will 
1. upload any new files to S3, validating the Etag to MD5
2. delete any old files 
3. optionally maintain old files that were part of earlier builds (downloading and parsing older `precache-manifest` files)
4. set the HTTP cache parameters for different files (i.e. cache files with hash keys, no cache for common files)
5. clear the CloudFront distribution (i.e. invalidation request)


# How to use

## Configuration

1. Copy `s3_deploy.cfg.template` to `s3_deploy.cfg` and add your configuration elements
   - **Note**: *You may have only one "product" and "deployment" to start*
3. Add a CloudFront distribution for each product and deployment
4. Add the AWS credentials that have permissions to add and remove S3 files for the configured bucket, and can create CloudFront invalidations

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

* **CloudFront front end** - for a custom domain, SSL traffic will go through CloudFront and not S3 (which does not permit SSL with a custom domain)
* **One to many** - a single S3 bucket can hold many deployments (e.g. testing, production). I set up each deployment with a dedicated CloudFront distribution pointing to the same bucket but a different prefix (e.g. deployments/testing, deployments/production)
* **Cross-domain API issues can be avoided** - there is a way to use CloudFront for both static files in S3 and a dynamic API, all in the same domain (see below)
* **Compression** - compression should always be enabled on CloudFront
* **Browser caching** - CRA build will create chunk files with hash keys.  These can be cached in the browser for long periods.  But files without hash keys like `index.html` should be set for no-caching.  These caching attributes can set through S3.

## Cross-domain API issues (CORS) - how to avoid

Each CloudFront distribution can have multiple origins.  One origin should be set to S3, while the other can be set to an API server or load balancer.  If the API server is within the AWS system, CloudFront can safely use non-SSL (port 80) to communicate as a proxy server.  

To use port 80, the API server must be configured to respond to the non-secure traffic (if traffic is only port 80, no SSL certificate is required). The Apache VirtualHost will use the hostname of CloudFront instance *not* the API server hostname (e.g. `my.react-app.com` not `my.api.com`) because the HTTP request Host value is not modified.

## How to enable and API with CloudFront:

1. Add your API server as an origin, HTTP only if within AWS
2. Add a new behavior, `/api/*` path pattern, HTTPS only viewer policy, all HTTP methods (unless you have GET only), `ALL` for **Cache Based on Selected Request Headers**, Compress Objects enabled, and **Forward All** for the query strings
3. Nothing should be cached by CloudFront (unless you can do this)

## How to enable React Router in CloudFront

To enable different paths in React Router, [set the the CloudFront error page][1] to be `/index.html` (so that all failed requests will go there):

1. Go to CloudFront distributions in the AWS console 
2. Click on the appropriate CloudFront distribution 
3. Click on Error Pages tab
4. Add error responses for `403: Forbidden` and `404: Not Found` pointing
    `/index.html` with HTTP response of `200`

# Testing

## Testing HTTP headers

You can view this HTTP header if your S3 bucket is set for static website hosting (note S3 website hosting is not required for CloudFront to work):

```curl -I http://MY-S3-ENDPOINT/index.html```

Likewise you can test the header from CloudFront:

```curl -I https://CLOUDFRONT-URL/index.html```

To test compression, add encoding acceptance to the request HTTP header, e.g.

```curl -H "Accept-Encoding: gzip" -I https://CLOUDFRONT-URL/index.html```

  [1]: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/custom-error-pages.html
