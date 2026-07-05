# Python client library - News API

Source: https://newsapi.org/docs/client-libraries/python

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