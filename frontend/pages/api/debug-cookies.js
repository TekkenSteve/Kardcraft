export default function handler(req, res) {
  const cookies = req.headers.cookie || 'No cookies';
  
  res.status(200).json({
    cookies: cookies,
    headers: req.headers,
    method: req.method,
    url: req.url
  });
}