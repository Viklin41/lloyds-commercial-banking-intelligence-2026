# C# client library - News API

Source: https://newsapi.org/docs/client-libraries/csharp

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