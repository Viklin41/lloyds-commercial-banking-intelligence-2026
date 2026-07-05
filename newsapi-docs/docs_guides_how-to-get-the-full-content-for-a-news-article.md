# How to get the full content for a news article - Documentation - News API

Source: https://newsapi.org/docs/guides/how-to-get-the-full-content-for-a-news-article

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