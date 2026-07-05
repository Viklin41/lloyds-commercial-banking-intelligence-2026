# Java client library - News API

Source: https://newsapi.org/docs/client-libraries/java

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