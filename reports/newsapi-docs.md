# NewsAPI Documentation

Crawled from https://newsapi.org/docs

---

# Documentation - News API

**Source:** https://newsapi.org/docs

*chevron\_right*

# Documentation

News API is a simple HTTP REST API for searching and retrieving live articles from all over the web. It can help you answer questions like:

* What top stories is TechCrunch running right now?
* What new articles were published about the next iPhone today?
* Has my company or product been mentioned or reviewed by any blogs recently?

You can search for articles with any combination of the following criteria:

* **Keyword or phrase**. Eg: find all articles containing the word 'Microsoft'.
* **Date published**. Eg: find all articles published yesterday.
* **Source domain name**. Eg: find all articles published on thenextweb.com.
* **Language**. Eg: find all articles written in English.

You can sort the results in the following orders:

* Date published
* Relevancy to search keyword
* Popularity of source

You need an API key to use the API - this is a unique key that identifies your requests. They're free while you're in development.

[Get API key](/register)

*help\_outline* If you are logged in you will see your live API key in all the examples.

---

[Authentication*arrow\_forward*](/docs/authentication)

---

# Authentication - Documentation - News API

**Source:** https://newsapi.org/docs/authentication

*chevron\_right*

# Authentication

Authentication is handled with a simple API key.

They're free while you are in development, and you can get one here:

[Get API key](/register)

You can attach your API key to a request in one of three ways:

* Via the `apiKey` querystring parameter.
* Via the `X-Api-Key` HTTP header.
* Via the `Authorization` HTTP header. Including `Bearer` is optional, and be sure not to base 64 encode it like you may have seen in other authentication tutorials.

We strongly recommend the either of last two so that your API key isn't visible to others in logs or via request sniffing.

If you don't append your API key correctly, or your API key is invalid, you will receive a `401 - Unauthorized` HTTP error.

---

[*arrow\_back*Documentation](/docs)
[Endpoints*arrow\_forward*](/docs/endpoints)

Via querystring

```
GET https://newsapi.org/v2/everything?q=keyword&apiKey=API_KEY
```

Via X-Api-Key HTTP header

```
X-Api-Key: API_KEY
```

Via Authorization HTTP header

```
Authorization: API_KEY
```

---

# Client libraries - Documentation - News API

**Source:** https://newsapi.org/docs/client-libraries

*chevron\_right*

# Client libraries

Use a client library (SDK) to quickly and easily get started with News API without having to make HTTP requests directly.

We have libraries for the following languages:

* [Node.js](/docs/client-libraries/node-js)
* [Ruby](/docs/client-libraries/ruby)
* [Python](/docs/client-libraries/python)
* [PHP coming soon](#)
* [Java coming soon](#)
* [C#](/docs/client-libraries/csharp)

---

[*arrow\_back*Errors](/docs/errors)
[Guides*arrow\_forward*](/docs/guides)

---

# C# client library - News API

**Source:** https://newsapi.org/docs/client-libraries/csharp

*chevron\_right*

[Star](https://github.com/news-api-gh/news-api-csharp)

# C# client library

Use our C# client library to integrate News API into your C# application without having to make HTTP requests directly.

The C# client library is available on Nuget.

Source:  [News-API-gh/News-API-csharp](https://github.com/News-API-gh/News-API-csharp)

Installation

```
PM> Install-Package NewsAPI
```

Usage

```
using NewsAPI;
using NewsAPI.Models;
using NewsAPI.Constants;
using System;

namespace MyApplication
{
    class Program
    {
        static void Main(string[] args)
        {
            // init with your API key
            var newsApiClient = new NewsApiClient("API_KEY");
            var articlesResponse = newsApiClient.GetEverything(new EverythingRequest
            {
                Q = "Apple",
                SortBy = SortBys.Popularity,
                Language = Languages.EN,
                From = new DateTime(2018, 1, 25)
            });
            if (articlesResponse.Status == Statuses.Ok)
            {
                // total results found
                Console.WriteLine(articlesResponse.TotalResults);
                // here's the first 20
                foreach (var article in articlesResponse.Articles)
                {
                    // title
                    Console.WriteLine(article.Title);
                    // author
                    Console.WriteLine(article.Author);
                    // description
                    Console.WriteLine(article.Description);
                    // url
                    Console.WriteLine(article.Url);
                    // published at
                    Console.WriteLine(article.PublishedAt);
                }
            }
            Console.ReadLine();
        }
    }
}
```

---

# Java client library - News API

**Source:** https://newsapi.org/docs/client-libraries/java

*chevron\_right*

# Java client library

Use the unofficial Java client library to integrate News API into your Java application without having to make HTTP requests directly.

Source: [![](/images/github.svg) KwabenBerko/News-API-Java](https://github.com/KwabenBerko/News-API-Java)

Installation

Step 1. Add the JitPack repository to your root build.gradle file.

```
allprojects {
  repositories {
    ...
    maven { url 'https://jitpack.io' }
  }
}
```

Step 2 : Download via Gradle:

```
implementation 'com.github.KwabenBerko:News-API-Java:1.0.0'
```

Usage

```
NewsApiClient newsApiClient = new NewsApiClient("YOUR_API_KEY");

// /v2/everything
newsApiClient.getEverything(
  new EverythingRequest.Builder()
          .q("trump")
          .build(),
  new NewsApiClient.ArticlesResponseCallback() {
      @Override
      public void onSuccess(ArticleResponse response) {
          System.out.println(response.getArticles().get(0).getTitle());
      }

      @Override
      public void onFailure(Throwable throwable) {
          System.out.println(throwable.getMessage());
      }
  }
);
        
// /v2/top-headlines
newsApiClient.getTopHeadlines(
  new TopHeadlinesRequest.Builder()
    .q("bitcoin")
    .language("en")
    .build(),
  new NewsApiClient.ArticlesResponseCallback() {
    @Override
    public void onSuccess(ArticleResponse response) {
      System.out.println(response.getArticles().get(0).getTitle());
    }

    @Override
    public void onFailure(Throwable throwable) {
      System.out.println(throwable.getMessage());
    }
  }
);
        
// /v2/top-headlines/sources
newsApiClient.getSources(
  new SourcesRequest.Builder()
    .language("en")
    .country("us")
    .build(),
  new NewsApiClient.SourcesCallback() {
    @Override
    public void onSuccess(SourcesResponse response) {
        System.out.println(response.getSources().get(0).getName());
    }

    @Override
    public void onFailure(Throwable throwable) {
      System.out.println(throwable.getMessage());
    }
  }
);
```

---

# Node.js client library - News API

**Source:** https://newsapi.org/docs/client-libraries/node-js

*chevron\_right*

# Node.js client library

Use the unofficial Node.js client library to integrate News API into your Node.js application without having to make HTTP requests directly.

Source:  [bzarras/newsapi](https://github.com/bzarras/newsapi)

Installation

```
$ npm install newsapi --save
```

Usage

```
const NewsAPI = require('newsapi');
const newsapi = new NewsAPI('API_KEY');
// To query /v2/top-headlines
// All options passed to topHeadlines are optional, but you need to include at least one of them
newsapi.v2.topHeadlines({
  sources: 'bbc-news,the-verge',
  q: 'bitcoin',
  category: 'business',
  language: 'en',
  country: 'us'
}).then(response => {
  console.log(response);
  /*
    {
      status: "ok",
      articles: [...]
    }
  */
});
// To query /v2/everything
// You must include at least one q, source, or domain
newsapi.v2.everything({
  q: 'bitcoin',
  sources: 'bbc-news,the-verge',
  domains: 'bbc.co.uk, techcrunch.com',
  from: '2017-12-01',
  to: '2017-12-12',
  language: 'en',
  sortBy: 'relevancy',
  page: 2
}).then(response => {
  console.log(response);
  /*
    {
      status: "ok",
      articles: [...]
    }
  */
});
// To query sources
// All options are optional
newsapi.v2.sources({
  category: 'technology',
  language: 'en',
  country: 'us'
}).then(response => {
  console.log(response);
  /*
    {
      status: "ok",
      sources: [...]
    }
  */
});
```

---

# PHP client library - News API

**Source:** https://newsapi.org/docs/client-libraries/php

*chevron\_right*

# PHP client library

Use the unofficial PHP client library to integrate News API into your PHP application without having to make HTTP requests directly.

Source: [![](/images/github.svg) jcobhams/newsapi-php](https://github.com/jcobhams/newsapi-php)

Installation

```
$ composer require jcobhams/newsapi
```

Usage

```
use jcobhams\NewsApi\NewsApi;

$newsapi = new NewsApi($your_api_key);

# /v2/everything
$all_articles = $newsapi->getEverything($q, $sources, $domains, $exclude_domains, $from, $to, $language, $sort_by,  $page_size, $page);

# /v2/top-headlines
$top_headlines = $newsapi->getTopHeadlines($q, $sources, $country, $category, $page_size, $page);

# /v2/top-headlines/sources
$sources = $newsapi->getSources($category, $language, $country)
```

---

# Python client library - News API

**Source:** https://newsapi.org/docs/client-libraries/python

*chevron\_right*

# Python client library

Use the unofficial Python client library to integrate News API into your Python application without having to make HTTP requests directly.

Source:  [mattlisiv/newsapi-python](https://github.com/mattlisiv/newsapi-python)

Installation

```
$ pip install newsapi-python
```

Usage

```
from newsapi import NewsApiClient

# Init
newsapi = NewsApiClient(api_key='API_KEY')

# /v2/top-headlines
top_headlines = newsapi.get_top_headlines(q='bitcoin',
                                          sources='bbc-news,the-verge',
                                          category='business',
                                          language='en',
                                          country='us')

# /v2/everything
all_articles = newsapi.get_everything(q='bitcoin',
                                      sources='bbc-news,the-verge',
                                      domains='bbc.co.uk,techcrunch.com',
                                      from_param='2017-12-01',
                                      to='2017-12-12',
                                      language='en',
                                      sort_by='relevancy',
                                      page=2)

# /v2/top-headlines/sources
sources = newsapi.get_sources()
```

---

# Ruby client library - News API

**Source:** https://newsapi.org/docs/client-libraries/ruby

*chevron\_right*

# Ruby client library

Use the unofficial Ruby client library to integrate News API into your Ruby application without having to make HTTP requests directly.

Source:  [olegmikhnovich/News-API-ruby](https://github.com/olegmikhnovich/News-API-ruby)

Installation

```
$ gem install news-api
```

Usage

```
require 'news-api'

# Init
newsapi = News.new("API_KEY")             

# /v2/top-headlines
top_headlines = newsapi.get_top_headlines(q: 'bitcoin',
                                          sources: 'bbc-news,the-verge',
                                          category: 'business',
                                          language: 'en',
                                          country: 'us')

# /v2/everything
all_articles = newsapi.get_everything(q: 'bitcoin',
                                      sources: 'bbc-news,the-verge',
                                      domains: 'bbc.co.uk,techcrunch.com',
                                      from: '2017-12-01',
                                      to: '2017-12-12',
                                      language: 'en',
                                      sortBy: 'relevancy',
                                      page: 2))

# /v2/top-headlines/sources
sources = newsapi.get_sources(country: 'us', language: 'en')
```

---

# Endpoints - Documentation - News API

**Source:** https://newsapi.org/docs/endpoints

*chevron\_right*

# Endpoints

News API has 2 main endpoints:

* [Everything](/docs/endpoints/everything) `/v2/everything` – search every article published by over 5,000 different sources large and small in the last 5 years. This endpoint is ideal for news analysis and article discovery.
* [Top headlines](/docs/endpoints/top-headlines) `/v2/top-headlines` – returns breaking news headlines for countries, categories, and singular publishers. This is perfect for use with news tickers or anywhere you want to use live up-to-date news headlines.

There is also a minor endpoint that can be used to retrieve a small subset of the publishers we can scan:

* [Sources](/docs/endpoints/sources) `/v2/top-headlines/sources` – returns information (including name, description, and category) about the most notable sources available for obtaining top headlines from. This list could be piped directly through to your users when showing them some of the options available.

---

[*arrow\_back*Authentication](/docs/authentication)
[Endpoint *arrow\_right* Everything*arrow\_forward*](/docs/endpoints/everything)

---

# Everything - Documentation - News API

**Source:** https://newsapi.org/docs/endpoints/everything

*chevron\_right*

# Everything /v2/everything

Search through millions of articles from over 5,000 large and small news sources and blogs.

This endpoint suits article discovery and analysis.

## Request parameters

* ### apiKey required

  Your API key. Alternatively you can provide this via the `X-Api-Key` HTTP header.
* ### q

  Keywords or phrases to search for in the article title and body.

  Advanced search is supported here:

  + Surround phrases with quotes (") for exact match.
  + Prepend words or phrases that *must* appear with a + symbol. Eg: +bitcoin
  + Prepend words that *must not* appear with a - symbol. Eg: -bitcoin
  + Alternatively you can use the AND / OR / NOT keywords, and optionally group these with parenthesis. Eg: crypto AND (ethereum OR litecoin) NOT bitcoin.

  The complete value for `q` must be **URL-encoded**. Max length: 500 chars.
* ### searchIn

  The fields to restrict your `q` search to.

  The possible options are:

  + `title`
  + `description`
  + `content`

  Multiple options can be specified by separating them with a comma, for example: `title,content`.

  This parameter is useful if you have an edge case where searching all the fields is not giving the desired outcome, but generally you should not need to set this.
    
    
  Default: all fields are searched.
* ### sources

  A comma-seperated string of identifiers (maximum 20) for the news sources or blogs you want headlines from. Use the [/sources](#sources) endpoint to locate these programmatically or look at the [sources index](/sources).
* ### domains

  A comma-seperated string of domains (eg bbc.co.uk, techcrunch.com, engadget.com) to restrict the search to.
* ### excludeDomains

  A comma-seperated string of domains (eg bbc.co.uk, techcrunch.com, engadget.com) to remove from the results.
* ### from

  A date and optional time for the *oldest* article allowed. This should be in ISO 8601 format (e.g. `2026-06-26` or `2026-06-26T08:19:04`)
    
    
  Default: the oldest according to your plan.
* ### to

  A date and optional time for the *newest* article allowed. This should be in ISO 8601 format (e.g. `2026-06-26` or `2026-06-26T08:19:04`)
    
    
  Default: the newest according to your plan.
* ### language

  The 2-letter ISO-639-1 code of the language you want to get headlines for. Possible options: `ar``de``en``es``fr``he``it``nl``no``pt``ru``sv``ud``zh`.
    
    
  Default: all languages returned.
* ### sortBy

  The order to sort the articles in. Possible options: `relevancy`, `popularity`, `publishedAt`.  
  `relevancy` = articles more closely related to `q` come first.  
  `popularity` = articles from popular sources and publishers come first.  
  `publishedAt` = newest articles come first.
    
    
  Default: `publishedAt`
* ### pageSize int

  The number of results to return per page.
    
    
  Default: `100`. Maximum: `100`.
* ### page int

  Use this to page through the results.
    
    
  Default: `1`.

## Response object

* ### status string

  If the request was successful or not. Options: `ok`, `error`. In the case of `error` a `code` and `message` property will be populated.
* ### totalResults int

  The total number of results available for your request. Only a limited number are shown at a time though, so use the `page` parameter in your requests to page through them.
* ### articles array[article]

  The results of the request.

  + ### source object

    The identifier `id` and a display name `name` for the source this article came from.
  + ### author string

    The author of the article
  + ### title string

    The headline or title of the article.
  + ### description string

    A description or snippet from the article.
  + ### url string

    The direct URL to the article.
  + ### urlToImage string

    The URL to a relevant image for the article.
  + ### publishedAt string

    The date and time that the article was published, in UTC (+000)
  + ### content string

    The unformatted content of the article, where available. This is truncated to 200 chars.

---

[*arrow\_back*Endpoints](/docs/endpoints)
[Endpoint *arrow\_right* Top Headlines*arrow\_forward*](/docs/endpoints/top-headlines)

Live examples

All articles about Bitcoin

Definition

```
GET https://newsapi.org/v2/everything?q=bitcoin&apiKey=API_KEY
```

Example response

---

All articles mentioning Apple from yesterday, sorted by popular publishers first

Definition

```
GET https://newsapi.org/v2/everything?q=apple&from=2026-06-25&to=2026-06-25&sortBy=popularity&apiKey=API_KEY
```

Example response

---

All articles published by TechCrunch and The Next Web

Definition

```
GET https://newsapi.org/v2/everything?domains=techcrunch.com,thenextweb.com&apiKey=API_KEY
```

Example response

---

Error example

Definition

```
GET https://newsapi.org/v2/everything
```

Example response

---

---

# Sources - Documentation - News API

**Source:** https://newsapi.org/docs/endpoints/sources

*chevron\_right*

# Sources /v2/top-headlines/sources

This endpoint returns the subset of news publishers that top headlines (`/v2/top-headlines`) are available from. It's mainly a convenience endpoint that you can use to keep track of the publishers available on the API, and you can pipe it straight through to your users.

## Request parameters

* ### apiKey required

  Your API key. Alternatively you can provide this via the `X-Api-Key` HTTP header.
* ### category

  Find sources that display news of this category. Possible options: `business``entertainment``general``health``science``sports``technology`. Default: all categories.
* ### language

  Find sources that display news in a specific language. Possible options: `ar``de``en``es``fr``he``it``nl``no``pt``ru``sv``ud``zh`. Default: all languages.
* ### country

  Find sources that display news in a specific country. Possible options: `ae``ar``at``au``be``bg``br``ca``ch``cn``co``cu``cz``de``eg``fr``gb``gr``hk``hu``id``ie``il``in``it``jp``kr``lt``lv``ma``mx``my``ng``nl``no``nz``ph``pl``pt``ro``rs``ru``sa``se``sg``si``sk``th``tr``tw``ua``us``ve``za`. Default: all countries.

## Response object

* ### status string

  If the request was successful or not. Options: `ok`, `error`. In the case of `error` a `code` and `message` property will be populated.
* ### sources array[source]

  The results of the request.

  + ### id string

    The identifier of the news source. You can use this with our other endpoints.
  + ### name string

    The name of the news source
  + ### description string

    A description of the news source
  + ### url string

    The URL of the homepage.
  + ### category string

    The type of news to expect from this news source.
  + ### language string

    The language that this news source writes in.
  + ### country string

    The country this news source is based in (and primarily writes about).

---

[*arrow\_back*Endpoint *arrow\_right* Top Headlines](/docs/endpoints/top-headlines)
[Errors*arrow\_forward*](/docs/errors)

All sources

Definition

```
GET https://newsapi.org/v2/top-headlines/sources?apiKey=API_KEY
```

Example response

---

Just Business sources

Definition

```
GET https://newsapi.org/v2/top-headlines/sources?category=businessapiKey=API_KEY
```

Example response

---

Sources in the US

Definition

```
GET https://newsapi.org/v2/top-headlines/sources?country=usapiKey=API_KEY
```

Example response

---

# Top headlines - Documentation - News API

**Source:** https://newsapi.org/docs/endpoints/top-headlines

*chevron\_right*

# Top headlines /v2/top-headlines

This endpoint provides live top and breaking headlines for a country, specific category in a country, single source, or multiple sources. You can also search with keywords. Articles are sorted by the earliest date published first.

This endpoint is great for retrieving headlines for use with news tickers or similar.

## Request parameters

* ### apiKey required

  Your API key. Alternatively you can provide this via the `X-Api-Key` HTTP header.
* ### country

  The 2-letter ISO 3166-1 code of the country you want to get headlines for. Possible options: `us`. Note: you can't mix this param with the `sources` param.
* ### category

  The category you want to get headlines for. Possible options: `business``entertainment``general``health``science``sports``technology`. Note: you can't mix this param with the `sources` param.
* ### sources

  A comma-seperated string of identifiers for the news sources or blogs you want headlines from. Use the [/top-headlines/sources](/docs/endpoints/sources) endpoint to locate these programmatically or look at the [sources index](/sources). Note: you can't mix this param with the `country` or `category` params.
* ### q

  Keywords or a phrase to search for.
* ### pageSize int

  The number of results to return per page (request). 20 is the default, 100 is the maximum.
* ### page int

  Use this to page through the results if the total results found is greater than the page size.

## Response object

* ### status string

  If the request was successful or not. Options: `ok`, `error`. In the case of `error` a `code` and `message` property will be populated.
* ### totalResults int

  The total number of results available for your request.
* ### articles array[article]

  The results of the request.

  + ### source object

    The identifier `id` and a display name `name` for the source this article came from.
  + ### author string

    The author of the article
  + ### title string

    The headline or title of the article.
  + ### description string

    A description or snippet from the article.
  + ### url string

    The direct URL to the article.
  + ### urlToImage string

    The URL to a relevant image for the article.
  + ### publishedAt string

    The date and time that the article was published, in UTC (+000)
  + ### content string

    The unformatted content of the article, where available. This is truncated to 200 chars.

---

[*arrow\_back*Endpoint *arrow\_right* Everything](/docs/endpoints/everything)
[Endpoint *arrow\_right* Top Headlines *arrow\_right* Sources*arrow\_forward*](/docs/endpoints/sources)

Live examples

Top headlines in the US

Definition

```
GET https://newsapi.org/v2/top-headlines?country=us&apiKey=API_KEY
```

Example response

---

Top headlines from BBC News

Definition

```
GET https://newsapi.org/v2/top-headlines?sources=bbc-news&apiKey=API_KEY
```

Example response

---

Top business headlines from Germany

Definition

```
GET https://newsapi.org/v2/top-headlines?country=de&category=business&apiKey=API_KEY
```

Example response

---

Top headlines about Trump

Definition

```
GET https://newsapi.org/v2/top-headlines?q=trump&apiKey=API_KEY
```

Example response

---

Error example

Definition

```
GET https://newsapi.org/v2/top-headlines
```

Example response

---

---

# Errors - Documentation - News API

**Source:** https://newsapi.org/docs/errors

*chevron\_right*

# Errors

If you make a bad request we'll let you know by returning a relevant HTTP status code along with more details in the body.

## Response object

* ### status string

  If the request was successful or not. Options: `ok`, `error`. In the case of `ok`, the below two properties will not be present.
* ### code string

  A short code identifying the type of error returned.
* ### message string

  A fuller description of the error, usually including how to fix it.

## HTTP status codes summary

* `200 - OK`. The request was executed successfully.
* `400 - Bad Request`. The request was unacceptable, often due to a missing or misconfigured parameter.
* `401 - Unauthorized`. Your API key was missing from the request, or wasn't correct.
* `429 - Too Many Requests`. You made too many requests within a window of time and have been rate limited. Back off for a while.
* `500 - Server Error`. Something went wrong on our side.

## Error codes

When an HTTP error is returned we populate the `code` and `message` properties in the response containing more information. Here are the possible options:

* `apiKeyDisabled` - Your API key has been disabled.
* `apiKeyExhausted` - Your API key has no more requests available.
* `apiKeyInvalid` - Your API key hasn't been entered correctly. Double check it and try again.
* `apiKeyMissing` - Your API key is missing from the request. Append it to the request with [one of these methods](/docs/authentication).
* `parameterInvalid` - You've included a parameter in your request which is currently not supported. Check the `message` property for more details.
* `parametersMissing` - Required parameters are missing from the request and it cannot be completed. Check the `message` property for more details.
* `rateLimited` - You have been rate limited. Back off for a while before trying the request again.
* `sourcesTooMany` - You have requested too many sources in a single request. Try splitting the request into 2 smaller requests.
* `sourceDoesNotExist` - You have requested a source which does not exist.
* `unexpectedError` - This shouldn't happen, and if it does then it's our fault, not yours. Try the request again shortly.

---

[*arrow\_back*Endpoint *arrow\_right* Sources](/docs/endpoints/sources)
[Client Libraries*arrow\_forward*](/docs/client-libraries)

Live examples

Missing API key example

Definition

```
GET https://newsapi.org/v2/everything?q=bitcoin
```

Example response

---

---

# Get started - Documentation - News API

**Source:** https://newsapi.org/docs/get-started

*chevron\_right*

curl
javascript
Ruby
Python
.NET

# Get started

To get started you'll need an API key. They're free while you are in development.

[Get API key](/register)

You should know how to make web requests in your chosen programming language. We have included some crude ways to do this in our examples below if you need a place to start. Alternatively you can use one of our [client libraries](/docs/client-libraries).

Now let's consider two of the most popular use cases for News API and walk through each one:

[Search for articles on the web that mention a keyword or phrase](#search)
[Get the current top headlines for a country, category, or publisher](#top-headlines)

## Search for news articles that mention a specific topic or keyword

The main use of News API is to search through every article published by over 5,000 news sources and blogs in the last 5 years. Think of us as Google News that you can interact with programmatically!

In this example we want to find all articles that mention Apple published today, and sort them by most popular source first (i.e. Engadget articles will be returned ahead of Mom and Pop's Little iPhone Blog). For this we need to use the `/everything` endpoint.

For more information about the `/everything` endpoint, including valid parameters for narrowing your search, see the [Everything endpoint reference](/docs/endpoints/everything).

Definition

```
GET https://newsapi.org/v2/everything?q=Apple&from=2026-06-26&sortBy=popularity&apiKey=API_KEY
```

Example request

```
curl https://newsapi.org/v2/everything -G \
    -d q=Apple \
    -d from=2026-06-26 \
    -d sortBy=popularity \
    -d apiKey=API_KEY
```

```
var url = 'https://newsapi.org/v2/everything?' +
          'q=Apple&' +
          'from=2026-06-26&' +
          'sortBy=popularity&' +
          'apiKey=API_KEY';

var req = new Request(url);

fetch(req)
    .then(function(response) {
        console.log(response.json());
    })
```

```
require 'open-uri'

url = 'https://newsapi.org/v2/everything?'\
      'q=Apple&'\
      'from=2026-06-26&'\
      'sortBy=popularity&'\
      'apiKey=API_KEY'

req = open(url)

response_body = req.read

puts response_body
```

```
import requests

url = ('https://newsapi.org/v2/everything?'
       'q=Apple&'
       'from=2026-06-26&'
       'sortBy=popularity&'
       'apiKey=API_KEY')

response = requests.get(url)

print r.json
```

```
using System.Net;
                            
var url = "https://newsapi.org/v2/everything?" +
          "q=Apple&" +
          "from=2026-06-26&" +
          "sortBy=popularity&" +
          "apiKey=API_KEY";
                            
var json = new WebClient().DownloadString(url);
                            
Console.WriteLine(json);
```

Example response

## Get the current top headlines for a country or category

News API is great as a data source for news tickers and other applications where you want to show your users live headlines. We track headlines in 7 categories across over 50 countries, and at over a hundred top publications and blogs, in near real time.

Let's make a request to get live top headlines in the US right now. We'll use the `/top-headlines` endpoint for this.

This returns a JSON object with the results in an array we can iterate over.

For more information about the `/top-headlines` endpoint, including valid parameters for focusing on specific countries and categories, see the [Top Headlines endpoint reference](/docs/endpoints/top-headlines).

Definition

```
GET https://newsapi.org/v2/top-headlines?country=us&apiKey=API_KEY
```

Example request

```
curl https://newsapi.org/v2/top-headlines -G \
    -d country=us \
    -d apiKey=API_KEY
```

```
var url = 'https://newsapi.org/v2/top-headlines?' +
          'country=us&' +
          'apiKey=API_KEY';
var req = new Request(url);
fetch(req)
    .then(function(response) {
        console.log(response.json());
    })
```

```
require 'open-uri'
url = 'https://newsapi.org/v2/top-headlines?'\
      'country=us&'\
      'apiKey=API_KEY'
req = open(url)
response_body = req.read
puts response_body
```

```
import requests
url = ('https://newsapi.org/v2/top-headlines?'
       'country=us&'
       'apiKey=API_KEY')
response = requests.get(url)
print response.json()
```

```
using System.Net;
                            
var url = "https://newsapi.org/v2/top-headlines?" +
          "country=us&" +
          "apiKey=API_KEY";
                            
var json = new WebClient().DownloadString(url);
                            
Console.WriteLine(json);
```

Example response

If you want headlines just from a specific source, for example BBC News, we can do that too.

The identifier for BBC News is `bbc-news`, which we can get by querying the [sources endpoint](/docs/endpoints/sources).

Definition

```
GET https://newsapi.org/v2/top-headlines?sources=bbc-news&apiKey=API_KEY
```

Example request

```
curl https://newsapi.org/v2/top-headlines -G \
    -d sources=bbc-news \
    -d apiKey=API_KEY
```

```
var url = 'https://newsapi.org/v2/top-headlines?' +
          'sources=bbc-news&' +
          'apiKey=API_KEY';
var req = new Request(url);
fetch(req)
    .then(function(response) {
        console.log(response.json());
    })
```

```
require 'open-uri'
url = 'https://newsapi.org/v2/top-headlines?'\
      'sources=bbc-news&'\
      'apiKey=API_KEY'
req = open(url)
response_body = req.read
puts response_body
```

```
import requests
url = ('https://newsapi.org/v2/top-headlines?'
       'sources=bbc-news&'
       'apiKey=API_KEY')
response = requests.get(url)
print response.json()
```

```
using System.Net;
                            
var url = "https://newsapi.org/v2/top-headlines?" +
          "sources=bbc-news&" +
          "apiKey=API_KEY";
                            
var json = new WebClient().DownloadString(url);
                            
Console.WriteLine(json);
```

Example response

For more details about the endpoints and modifiers you can lookup articles with, including possible responses, check [the full documentation](/docs).

---

# Guides - Documentation - News API

**Source:** https://newsapi.org/docs/guides

*chevron\_right*

# Guides

By now you may be familiar with the API and how to make requests, but still have questions about how to use the API as a component in your application, or how to use it to achieve your objectives.

Here we aim to answer common questions we get that should help you to extract greater value from the API.

---

[*arrow\_back*Client Libraries](/docs/client-libraries)
[Guides *arrow\_right* How to get the full article content from a news article*arrow\_forward*](/docs/guides/how-to-get-the-full-content-for-a-news-article)

---

# How to get the full content for a news article - Documentation - News API

**Source:** https://newsapi.org/docs/guides/how-to-get-the-full-content-for-a-news-article

*chevron\_right*

# How to get the full content for a news article

We don't provide the full article content with our search results, but it is possible for you to scrape the content yourself using the URL included with each result.

Doing this takes two steps:

1. Download the HTML of the page that the article is located on
2. Isolate the article content from the rest of the page (header, footer, ads, comments, related stories etc)

Fortunately there are open-source libraries available in every programming language that can help you do this in just a few lines of code.

---

## Node.js

---

```
# Install the libs we are going to use in our example:
npm install axios jsdom @mozilla/readability
```

```
// we need axios to make HTTP requests
const axios = require('axios');

// and we need jsdom and Readability to parse the article HTML
const { JSDOM } = require('jsdom');
const { Readability } = require('@mozilla/readability');

// First lets get some search data from News API

// Build the URL we are going request. This will get articles related to Apple and sort them newest first
let url = 'https://newsapi.org/v2/everything?' +
'q=Apple&' +
'sortBy=publishedAt&' +
'apiKey=API_KEY';

// Make the request with axios' get() function
axios.get(url).then(function(r1) {

  // At this point we will have some search results from the API. Take the first search result...
  let firstResult = r1.data.articles[0];

  // ...and download the HTML for it, again with axios
  axios.get(firstResult.url).then(function(r2) {

    // We now have the article HTML, but before we can use Readability to locate the article content we need jsdom to convert it into a DOM object
    let dom = new JSDOM(r2.data, {
      url: firstResult.url
    });

    // now pass the DOM document into readability to parse
    let article = new Readability(dom.window.document).parse();

    // Done! The article content is in the textContent property
    console.log(article.textContent);
  })
})
```

## Python

Coming soon.

---

[*arrow\_back*Guides](/docs/guides)

---

