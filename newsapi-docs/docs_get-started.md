# Get started - Documentation - News API

Source: https://newsapi.org/docs/get-started

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