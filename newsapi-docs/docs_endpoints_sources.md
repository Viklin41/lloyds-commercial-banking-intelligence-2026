# Sources - Documentation - News API

Source: https://newsapi.org/docs/endpoints/sources

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