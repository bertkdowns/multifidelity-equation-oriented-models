// Feed declarations are data. Loading one never loads or executes Python.
const fields = ['config', 'name', 'provider_type'];
function text(value) { return typeof value === 'string' && !!value.trim(); }
function jsonValue(value) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(jsonValue);
  return typeof value === 'object' && Object.values(value).every(jsonValue);
}
export function parseFeeds(source) {
  const document = JSON.parse(source);
  if (!document || typeof document !== 'object' || Array.isArray(document) || Object.keys(document).join(',') !== 'feeds' || !Array.isArray(document.feeds))
    throw Error('Expected a feed document containing a feeds array.');
  const feeds = document.feeds;
  const names = new Set();
  for (const feed of feeds) {
    if (!feed || typeof feed !== 'object' || Array.isArray(feed) || Object.keys(feed).sort().join(',') !== fields.join(','))
      throw Error('A feed contains name, provider_type and config.');
    if (!text(feed.name) || !text(feed.provider_type)) throw Error('Feed name and provider_type must be nonempty strings.');
    if (names.has(feed.name)) throw Error(`Duplicate feed name: ${feed.name}`);
    names.add(feed.name);
    if (!feed.config || typeof feed.config !== 'object' || Array.isArray(feed.config) || !jsonValue(feed.config))
      throw Error('Feed config must be a finite JSON object.');
  }
  return document;
}

export function updateFeed(document, name, config) {
  if (!config || typeof config !== 'object' || Array.isArray(config) || !jsonValue(config))
    throw Error('Feed config must be a finite JSON object.');
  const feeds = document.feeds;
  if (!feeds.some(p => p.name === name)) throw Error(`Unknown feed: ${name}`);
  return parseFeeds(JSON.stringify({ feeds: feeds.map(p => p.name === name ? { ...p, config } : p) }));
}
