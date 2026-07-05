# Authentication - Documentation - News API

Source: https://newsapi.org/docs/authentication

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