import { defineConfig } from 'vite';
import fs from 'fs';
import path from 'path';

export default defineConfig({
  plugins: [
    {
      name: 'favorites-api',
      configureServer(server) {
        // Parse JSON body middleware
        server.middlewares.use((req, res, next) => {
          if (req.method === 'POST' && req.url === '/api/favorites') {
            let body = '';
            req.on('data', chunk => {
              body += chunk.toString();
            });
            req.on('end', () => {
              req.body = JSON.parse(body);
              next();
            });
          } else {
            next();
          }
        });

        // Favorites endpoint
        server.middlewares.use('/api/favorites', (req, res) => {
          if (req.method === 'POST') {
            const { store, id, action } = req.body;
            if (!store || !id || !action) {
              res.statusCode = 400;
              return res.end(JSON.stringify({ error: 'Faltan parámetros' }));
            }

            // Path to tiendas folder
            const tiendasDir = path.resolve(__dirname, '../tiendas');
            const favPath = path.join(tiendasDir, store, 'datos', 'favoritos.json');
            
            // Ensure directory exists
            const dir = path.dirname(favPath);
            if (!fs.existsSync(dir)) {
              fs.mkdirSync(dir, { recursive: true });
            }

            let favorites = [];
            if (fs.existsSync(favPath)) {
              try {
                favorites = JSON.parse(fs.readFileSync(favPath, 'utf-8'));
              } catch (e) {
                console.error("Error parsing favoritos.json:", e);
                favorites = [];
              }
            }

            if (action === 'add') {
              if (!favorites.includes(id)) {
                favorites.push(id);
              }
            } else if (action === 'remove') {
              favorites = favorites.filter(favId => favId !== id);
            }

            fs.writeFileSync(favPath, JSON.stringify(favorites, null, 2), 'utf-8');
            
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ success: true, favorites }));
          } else if (req.method === 'GET') {
            const tiendasDir = path.resolve(__dirname, '../tiendas');
            const allFavorites = {};
            
            if (fs.existsSync(tiendasDir)) {
              const tiendas = fs.readdirSync(tiendasDir);
              for (const tienda of tiendas) {
                const favPath = path.join(tiendasDir, tienda, 'datos', 'favoritos.json');
                if (fs.existsSync(favPath)) {
                  try {
                    const favs = JSON.parse(fs.readFileSync(favPath, 'utf-8'));
                    if (favs.length > 0) {
                      allFavorites[tienda] = favs;
                    }
                  } catch (e) {
                    console.error("Error parsing favoritos for", tienda, e);
                  }
                }
              }
            }
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ success: true, data: allFavorites }));
          }
        });
      }
    }
  ],
  server: {
    allowedHosts: [
      'sunshine-baseball-packed-analog.trycloudflare.com'
    ]
  }
});
