# Ruby client library - News API

Source: https://newsapi.org/docs/client-libraries/ruby

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