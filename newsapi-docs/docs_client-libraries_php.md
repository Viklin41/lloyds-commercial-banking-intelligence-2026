# PHP client library - News API

Source: https://newsapi.org/docs/client-libraries/php

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