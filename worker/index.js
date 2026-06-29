/**
 * Cloudflare Worker proxy for dataconomy.com WP REST API.
 *
 * Deploy: npx wrangler deploy
 * Test:   curl https://YOUR-WORKER.workers.dev/wp-json/wp/v2/posts?per_page=1
 *
 * This worker proxies requests to dataconomy.com from Cloudflare's edge network,
 * bypassing WAF blocks that affect GitHub Actions US IPs.
 */

const TARGET_HOST = "dataconomy.com";

export default {
  async fetch(request) {
    const url = new URL(request.url);

    // Rewrite the request to target host
    const targetUrl = new URL(url.pathname + url.search, `https://${TARGET_HOST}`);

    const headers = new Headers(request.headers);
    headers.set("Host", TARGET_HOST);
    headers.set("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36");
    headers.set("Accept", "application/json");

    const response = await fetch(targetUrl.toString(), {
      method: request.method,
      headers: headers,
      redirect: "follow",
    });

    // Return with CORS headers
    const newHeaders = new Headers(response.headers);
    newHeaders.set("Access-Control-Allow-Origin", "*");

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: newHeaders,
    });
  },
};
