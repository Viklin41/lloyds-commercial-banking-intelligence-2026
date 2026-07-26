# Top headlines - Documentation - News API

Source: https://newsapi.org/docs/endpoints/top-headlines

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