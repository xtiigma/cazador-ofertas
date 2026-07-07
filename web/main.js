// State
let globalData = null;
let currentStore = null;
let currentCategory = null;
let currentProducts = [];
let filteredProducts = [];
let currentPage = 1;
const itemsPerPage = 24;
let onlyRealDiscount = false;
let onlyBestPrice = false;

// DOM Elements
const storeNav = document.getElementById('store-nav');
const productsGrid = document.getElementById('productsGrid');
const productsHeader = document.getElementById('productsHeader');
const categoryTitle = document.getElementById('categoryTitle');
const totalProductsCount = document.getElementById('totalProductsCount');
const lastUpdate = document.getElementById('lastUpdate');
const statsOverview = document.getElementById('statsOverview');
const searchInput = document.getElementById('searchInput');
const sortSelect = document.getElementById('sortSelect');
const pagination = document.getElementById('pagination');
const breadcrumb = document.getElementById('breadcrumb');
const realDiscountToggle = document.getElementById('realDiscountToggle');
const togglePill = document.getElementById('togglePill');
const bestPriceToggle = document.getElementById('bestPriceToggle');

const inicioBtn = document.getElementById('inicioBtn');

// Theme Toggle
const themeToggle = document.getElementById('themeToggle');
const themeIcon = document.getElementById('themeIcon');

function initTheme() {
  const savedTheme = localStorage.getItem('theme') || 'light';
  document.documentElement.setAttribute('data-theme', savedTheme);
  updateThemeIcon(savedTheme);

  themeToggle.addEventListener('click', () => {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    updateThemeIcon(newTheme);
  });
}

function updateThemeIcon(theme) {
  themeIcon.className = theme === 'light' ? 'bi bi-moon-fill' : 'bi bi-sun-fill';
}

// Fetch /api/favorites
async function toggleFavorite(storeId, productId, currentStatus, btnElement) {
  const newStatus = !currentStatus;
  const action = newStatus ? 'add' : 'remove';
  
  // Optimistic UI update
  btnElement.classList.toggle('is-favorite');
  btnElement.innerHTML = newStatus ? '<i class="bi bi-heart-fill"></i>' : '<i class="bi bi-heart"></i>';
  
  try {
    const res = await fetch('/api/favorites', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ store: storeId, id: productId, action })
    });
    
    if (!res.ok) throw new Error('Error guardando favorito');
    
    // Sincronizar localmente si estamos en una vista normal
    const product = currentProducts.find(p => p.id === productId);
    if(product) product.es_favorito = newStatus;

    // Actualizar la estructura global para que al cambiar de categoría siga ahí
    const storeObj = globalData.tiendas[storeId];
    if (storeObj) {
      if (newStatus) {
        // Añadir a la categoría ⭐ Favoritos
        if (!storeObj.categorias["⭐ Favoritos"]) storeObj.categorias["⭐ Favoritos"] = [];
        // Buscar el producto en cualquier otra categoría para copiarlo
        let fullProduct = null;
        Object.values(storeObj.categorias).forEach(catArray => {
          const found = catArray.find(p => p.id === productId);
          if (found) fullProduct = found;
        });
        if (fullProduct) {
          const exists = storeObj.categorias["⭐ Favoritos"].find(p => p.id === productId);
          if (!exists) storeObj.categorias["⭐ Favoritos"].push({...fullProduct, es_favorito: true});
        }
      } else {
        // Eliminar de ⭐ Favoritos
        if (storeObj.categorias["⭐ Favoritos"]) {
          storeObj.categorias["⭐ Favoritos"] = storeObj.categorias["⭐ Favoritos"].filter(p => p.id !== productId);
          if (storeObj.categorias["⭐ Favoritos"].length === 0) delete storeObj.categorias["⭐ Favoritos"];
        }
      }
      
      // Actualizar es_favorito en todas las copias del producto en esta tienda
      Object.values(storeObj.categorias).forEach(catArray => {
        catArray.forEach(p => {
          if (p.id === productId) p.es_favorito = newStatus;
        });
      });
      
      // Re-renderizar el sidebar para que aparezca/desaparezca la categoría ⭐ Favoritos si es necesario
      renderSidebar();
      
      // Si estamos VISTO LA CATEGORÍA ⭐ Favoritos, quitar la tarjeta si se desmarcó
      if (currentCategory === "⭐ Favoritos" && !newStatus) {
        currentProducts = currentProducts.filter(p => p.id !== productId);
        applyFiltersAndSort();
      }
    }
    
  } catch(e) {
    console.error(e);
    // Revert on error
    btnElement.classList.toggle('is-favorite');
    btnElement.innerHTML = currentStatus ? '<i class="bi bi-heart-fill"></i>' : '<i class="bi bi-heart"></i>';
  }
}

// Formatters
const formatPrice = (price) => {
  if (price === null || price === undefined) return '-';
  return new Intl.NumberFormat('es-PE', { style: 'currency', currency: 'PEN' }).format(price);
};

const calculateDiscount = (normal, offer) => {
  if (!normal || !offer || normal <= offer) return 0;
  return Math.round(((normal - offer) / normal) * 100);
};

// Historial compacto: cada registro es [fecha, precio_normal, precio_oferta]
const hPrecio = (h) => h[2] || h[1] || 0;  // precio_oferta || precio_normal

const historicalPrices = (product) =>
  (product.historial || []).map(hPrecio).filter(p => p > 0);

const medianOf = (arr) => {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};

/**
 * Determina si un producto tiene un descuento REAL:
 * el precio actual está por debajo de la MEDIANA histórica (el precio
 * típico observado). La mediana es inmune a picos atípicos y a inflaciones
 * pre-evento (Cyber Wow), que sí distorsionan el máximo y el promedio.
 */
const hasRealDiscount = (product) => {
  const precioActual = product.precio_oferta || product.precio_normal;
  if (!precioActual) return false;

  const precios = historicalPrices(product);
  if (precios.length < 2) return false;

  return calculateRealDiscount(product) >= 1;
};

/**
 * Calcula el % de descuento real respecto a la MEDIANA histórica
 * (cuánto menos pagas hoy que el precio típico registrado).
 */
const calculateRealDiscount = (product) => {
  const precioActual = product.precio_oferta || product.precio_normal;
  if (!precioActual) return 0;
  const precios = historicalPrices(product);
  if (precios.length < 2) return 0;
  const mediana = medianOf(precios);
  if (!mediana || mediana <= precioActual) return 0;
  return Math.round(((mediana - precioActual) / mediana) * 100);
};

/**
 * Percentil del precio de hoy dentro de todo el historial propio:
 * 0 = el más barato jamás visto, 100 = el más caro. Métrica honesta:
 * no afirma nada sobre la tienda, solo describe nuestra memoria.
 */
const pricePercentile = (product) => {
  const precioActual = product.precio_oferta || product.precio_normal;
  if (!precioActual) return null;
  const precios = historicalPrices(product);
  if (precios.length < 2) return null;
  const debajo = precios.filter(p => p < precioActual).length;
  return Math.round((debajo / precios.length) * 100);
};

/**
 * Determina si un producto está hoy en su MEJOR PRECIO HISTÓRICO:
 * el precio actual es igual o menor que todos los precios anteriores
 * (excluyendo el último registro, que ES el precio actual), y existe al
 * menos un precio anterior mayor — un precio que nunca cambió no cuenta.
 * A diferencia de la versión anterior (estrictamente menor), el badge no
 * se apaga mientras el precio siga en su piso histórico.
 */
const isBestPriceToday = (product) => {
  const precioActual = product.precio_oferta || product.precio_normal;
  if (!precioActual) return false;

  const historial = product.historial || [];
  if (historial.length < 2) return false;

  const preciosAnteriores = historial.slice(0, -1).map(hPrecio).filter(p => p > 0);
  if (preciosAnteriores.length === 0) return false;

  const minAnterior = Math.min(...preciosAnteriores);
  const huboMayor = preciosAnteriores.some(p => p > precioActual);

  return precioActual <= minAnterior && huboMayor;
};

/**
 * Cuántos días (registros consecutivos al final del historial) lleva el
 * producto en su precio mínimo. 1 = tocó fondo hoy; 3 = tercer día al piso.
 */
const daysAtMinimum = (product) => {
  const precioActual = product.precio_oferta || product.precio_normal;
  if (!precioActual) return 0;
  const historial = product.historial || [];
  let dias = 0;
  for (let i = historial.length - 1; i >= 0; i--) {
    const p = hPrecio(historial[i]);
    if (p > 0 && p <= precioActual * 1.001) dias++;
    else break;
  }
  return Math.max(dias, 1);
};

const formatDate = (isoString) => {
  const d = new Date(isoString);
  return d.toLocaleDateString('es-PE', { hour: '2-digit', minute: '2-digit' });
};

// Data Fetching
async function loadData() {
  try {
    const response = await fetch('/data.json');
    if (!response.ok) throw new Error('Error network');
    globalData = await response.json();
    
    // Sincronizar en tiempo real los favoritos desde la API
    try {
      const favRes = await fetch('/api/favorites');
      if (favRes.ok) {
        const favJson = await favRes.json();
        if (favJson.success && favJson.data) {
          syncFavoritesRealtime(favJson.data);
        }
      }
    } catch(e) {
      console.warn("No se pudo sincronizar favoritos en tiempo real:", e);
    }
    
    // Update Header Stats
    totalProductsCount.textContent = globalData.metadata.total_productos.toLocaleString('es-PE');
    lastUpdate.textContent = `Actualizado: ${formatDate(globalData.metadata.ultima_actualizacion)}`;
    
    renderSidebar();
    renderOverview();
  } catch (error) {
    console.error('Error cargando data:', error);
    storeNav.innerHTML = '<div class="empty-state"><i class="bi bi-exclamation-triangle"></i><p>Error cargando datos</p></div>';
  }
}

function syncFavoritesRealtime(favData) {
  // Recorrer las tiendas y actualizar el estado
  Object.entries(globalData.tiendas).forEach(([storeId, store]) => {
    const apiFavs = favData[storeId] || [];
    const favCatExists = !!store.categorias["⭐ Favoritos"];
    if (!favCatExists && apiFavs.length > 0) {
      store.categorias["⭐ Favoritos"] = [];
    }

    // Iterar todas las categorias de la tienda
    Object.entries(store.categorias).forEach(([catName, products]) => {
      // No iterar sobre la categoria de favoritos misma para evitar duplicar
      if (catName === "⭐ Favoritos") return; 
      
      products.forEach(p => {
        const isFav = apiFavs.includes(p.id);
        p.es_favorito = isFav;
        
        // Si es favorito y no esta en la categoría "⭐ Favoritos", lo agregamos
        if (isFav && store.categorias["⭐ Favoritos"]) {
          const alreadyInFavCat = store.categorias["⭐ Favoritos"].find(favP => favP.id === p.id);
          if (!alreadyInFavCat) {
            store.categorias["⭐ Favoritos"].push({...p, es_favorito: true});
          }
        }
      });
    });
    
    // Limpiar de "⭐ Favoritos" aquellos que ya no están en apiFavs
    if (store.categorias["⭐ Favoritos"]) {
      store.categorias["⭐ Favoritos"] = store.categorias["⭐ Favoritos"].filter(p => apiFavs.includes(p.id));
      if (store.categorias["⭐ Favoritos"].length === 0) {
        delete store.categorias["⭐ Favoritos"];
      }
    }
  });
}

// Render Sidebar Navigation
function renderSidebar() {
  storeNav.innerHTML = '';
  
  const tiendas = Object.entries(globalData.tiendas);
  
  tiendas.forEach(([storeId, storeData]) => {
    const storeGroup = document.createElement('div');
    storeGroup.className = 'store-group';
    
    // Total products in store
    let storeTotal = 0;
    Object.values(storeData.categorias).forEach(cat => storeTotal += cat.length);
    
    const storeBtn = document.createElement('button');
    storeBtn.className = 'store-btn';
    storeBtn.innerHTML = `
      <span>${storeData.nombre}</span>
      <i class="bi bi-chevron-down"></i>
    `;
    
    const catList = document.createElement('ul');
    catList.className = 'category-list';
    
    // Create 'All' category for store
    const allCatItem = document.createElement('li');
    allCatItem.className = 'category-item';
    allCatItem.innerHTML = `
      <button class="cat-btn" data-store="${storeId}" data-cat="all">
        Todo <span class="count-badge">${storeTotal}</span>
      </button>
    `;
    catList.appendChild(allCatItem);
    
    // Add categories
    const categorias = Object.entries(storeData.categorias).sort((a,b) => b[1].length - a[1].length);
    
    categorias.forEach(([catName, products]) => {
      const li = document.createElement('li');
      li.className = 'category-item';
      li.innerHTML = `
        <button class="cat-btn" data-store="${storeId}" data-cat="${catName}">
          ${catName} <span class="count-badge">${products.length}</span>
        </button>
      `;
      catList.appendChild(li);
    });
    
    storeGroup.appendChild(storeBtn);
    storeGroup.appendChild(catList);
    storeNav.appendChild(storeGroup);
    
    // Toggle Event
    storeBtn.addEventListener('click', () => {
      const isOpen = catList.classList.contains('open');
      // Close all
      document.querySelectorAll('.category-list').forEach(l => l.classList.remove('open'));
      document.querySelectorAll('.store-btn').forEach(b => b.classList.remove('active'));
      
      if (!isOpen) {
        catList.classList.add('open');
        storeBtn.classList.add('active');
      }
    });
  });

  // Add click events to category buttons
  document.querySelectorAll('.cat-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      
      const storeId = btn.getAttribute('data-store');
      const catName = btn.getAttribute('data-cat');
      
      selectCategory(storeId, catName);
    });
  });
}

// Show Overview (Home)
function renderOverview() {
  productsHeader.classList.add('hidden');
  productsGrid.innerHTML = '';
  pagination.classList.add('hidden');
  statsOverview.innerHTML = '';
  statsOverview.style.display = 'grid';
  
  breadcrumb.innerHTML = `<span>Vista General</span>`;
  
  // Cards per store
  Object.entries(globalData.tiendas).forEach(([id, store]) => {
    let count = 0;
    Object.values(store.categorias).forEach(c => count += c.length);
    
    const card = document.createElement('div');
    card.className = 'overview-card';
    card.innerHTML = `
      <div class="icon-box"><i class="bi bi-shop"></i></div>
      <div class="card-info">
        <h3>${store.nombre}</h3>
        <p>${count.toLocaleString('es-PE')}</p>
      </div>
    `;
    card.addEventListener('click', () => {
      // Simulate click on store button
      const storeBtn = document.querySelector(`.cat-btn[data-store="${id}"][data-cat="all"]`);
      if(storeBtn) {
        storeBtn.closest('.store-group').querySelector('.store-btn').click();
        storeBtn.click();
      }
    });
    statsOverview.appendChild(card);
  });
}

// Select Category
function selectCategory(storeId, catName) {
  currentStore = storeId;
  currentCategory = catName;
  statsOverview.style.display = 'none';
  productsHeader.classList.remove('hidden');
  
  // Gather products
  currentProducts = [];
  const storeData = globalData.tiendas[storeId];
  
  if (catName === 'all') {
    Object.values(storeData.categorias).forEach(arr => currentProducts.push(...arr));
    // Marcar cada producto con su tienda para favoritos
    currentProducts.forEach(p => p._storeId = storeId);
    categoryTitle.textContent = `Todos los productos en ${storeData.nombre}`;
    breadcrumb.innerHTML = `<span>${storeData.nombre}</span> <i class="bi bi-chevron-right"></i> <span class="highlight">Todo</span>`;
  } else {
    currentProducts = storeData.categorias[catName] || [];
    currentProducts.forEach(p => p._storeId = storeId);
    categoryTitle.textContent = catName;
    breadcrumb.innerHTML = `<span>${storeData.nombre}</span> <i class="bi bi-chevron-right"></i> <span class="highlight">${catName}</span>`;
  }
  
  applyFiltersAndSort();

  // Cerrar sidebar en móvil (también cierra el overlay)
  closeSidebar();
}

// Búsqueda global (sin tienda seleccionada)
function globalSearch(query) {
  if (!globalData || !query.trim()) {
    renderOverview();
    return;
  }

  currentStore = null;
  currentCategory = null;
  statsOverview.style.display = 'none';
  productsHeader.classList.remove('hidden');

  // Recoger TODOS los productos de TODAS las tiendas
  currentProducts = [];
  const q = query.toLowerCase();

  Object.entries(globalData.tiendas).forEach(([storeId, storeData]) => {
    Object.values(storeData.categorias).forEach(arr => {
      arr.forEach(p => {
        if (p.nombre.toLowerCase().includes(q) || (p.marca && p.marca.toLowerCase().includes(q))) {
          // Clonar para no mutar el original, y marcar con su tienda
          const pCopy = {...p, _storeId: storeId, _storeName: storeData.nombre};
          currentProducts.push(pCopy);
        }
      });
    });
  });

  categoryTitle.textContent = `Resultados para "${query}" — ${currentProducts.length.toLocaleString('es-PE')} productos`;
  breadcrumb.innerHTML = `<span>Búsqueda Global</span> <i class="bi bi-chevron-right"></i> <span class="highlight">${query}</span>`;

  applyFiltersAndSort();

  // Deseleccionar categorías activas en el sidebar
  document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
}

// Volver al inicio
function goHome() {
  currentStore = null;
  currentCategory = null;
  currentProducts = [];
  filteredProducts = [];
  searchInput.value = '';
  onlyRealDiscount = false;
  onlyBestPrice = false;
  realDiscountToggle.classList.remove('active');
  bestPriceToggle.classList.remove('active');

  // Deseleccionar todo en el sidebar
  document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.category-list').forEach(l => l.classList.remove('open'));
  document.querySelectorAll('.store-btn').forEach(b => b.classList.remove('active'));

  renderOverview();
  closeSidebar();
}

// Sort & Filter
function applyFiltersAndSort() {
  const query = searchInput.value.toLowerCase();
  
  filteredProducts = currentProducts.filter(p => {
    const matchesQuery = p.nombre.toLowerCase().includes(query) || (p.marca && p.marca.toLowerCase().includes(query));
    if (!matchesQuery) return false;
    // Filtro de descuento real: precio actual < mediana histórica (precio típico)
    if (onlyRealDiscount && !hasRealDiscount(p)) return false;
    // Filtro de mejor precio hoy: precio actual <= mínimo histórico anterior
    if (onlyBestPrice && !isBestPriceToday(p)) return false;
    return true;
  });
  
  const sortVal = sortSelect.value;
  filteredProducts.sort((a, b) => {
    if (sortVal === 'price_asc') {
      return (a.precio_oferta || a.precio_normal || 0) - (b.precio_oferta || b.precio_normal || 0);
    } else if (sortVal === 'price_desc') {
      return (b.precio_oferta || b.precio_normal || 0) - (a.precio_oferta || a.precio_normal || 0);
    } else if (sortVal === 'name_asc') {
      return a.nombre.localeCompare(b.nombre);
    } else if (sortVal === 'discount_desc') {
      // Al ordenar por descuento, priorizar el descuento real si el filtro está activo
      if (onlyRealDiscount) {
        const d1 = calculateRealDiscount(a);
        const d2 = calculateRealDiscount(b);
        return d2 - d1;
      }
      const d1 = calculateDiscount(a.precio_normal, a.precio_oferta);
      const d2 = calculateDiscount(b.precio_normal, b.precio_oferta);
      return d2 - d1;
    }
  });
  
  currentPage = 1;
  renderProducts();
}

// Render Products Grid
function renderProducts() {
  productsGrid.innerHTML = '';
  
  if (filteredProducts.length === 0) {
    productsGrid.innerHTML = `
      <div class="empty-state">
        <i class="bi bi-search"></i>
        <h3>No se encontraron productos</h3>
        <p>Intenta con otros términos de búsqueda.</p>
      </div>
    `;
    pagination.classList.add('hidden');
    return;
  }
  
  const start = (currentPage - 1) * itemsPerPage;
  const end = start + itemsPerPage;
  const paginatedItems = filteredProducts.slice(start, end);
  
  paginatedItems.forEach(p => {
    const card = document.createElement('div');
    card.className = 'product-card';
    
    const discount = calculateDiscount(p.precio_normal, p.precio_oferta);

    // Badges especiales solo se muestran cuando su filtro está activo.
    // Sin filtro activo → solo el badge rojo normal de la tienda (si aplica).
    let badgeHtml = '';
    if (onlyBestPrice && isBestPriceToday(p)) {
      // Badge dorado: % vs precio típico + cuántos días lleva en el piso
      const pct = calculateRealDiscount(p);
      const pctTxt = pct > 0 ? ` -${pct}%` : '';
      const dias = daysAtMinimum(p);
      const diasTxt = dias > 1 ? ` · ${dias}° día` : '';
      badgeHtml = `<div class="discount-badge best-price-badge" title="Precio más bajo registrado en el historial (${dias} día${dias > 1 ? 's' : ''} en el mínimo)"><i class="bi bi-trophy"></i>${pctTxt} Mín.${diasTxt}</div>`;
    } else if (onlyRealDiscount) {
      // Badge verde: % por debajo de la mediana histórica (precio típico)
      const realDiscount = calculateRealDiscount(p);
      if (realDiscount > 0) {
        const pctl = pricePercentile(p);
        const pctlTxt = pctl !== null ? ` — percentil ${pctl} de tu historial (0 = el más barato visto)` : '';
        badgeHtml = `<div class="discount-badge real-discount-badge" title="Precio actual por debajo del precio típico registrado (mediana)${pctlTxt}"><i class="bi bi-graph-down-arrow"></i> -${realDiscount}% vs típico</div>`;
      }
    } else if (discount > 0) {
      // Sin filtro activo: badge rojo normal si la tienda marca descuento
      badgeHtml = `<div class="discount-badge">-${discount}%</div>`;
    }
    
    const imgHtml = p.imagen 
      ? `<div class="product-img-wrapper">
           <img src="${p.imagen}" alt="${p.nombre}" class="product-img" loading="lazy" onerror="this.style.display='none'">
         </div>`
      : ``; // Sin contenedor de imagen si no hay imagen

    // Generar historial HTML — formato compacto: [fecha, precio_normal, precio_oferta]
    let historyHtml = '';
    if (p.historial && p.historial.length > 0) {
      const historyItems = p.historial.map(h => {
        const precio = formatPrice(h[2] || h[1]);  // precio_oferta || precio_normal
        const dateParts = h[0].split('-');  // fecha
        const shortDate = dateParts.length === 3 ? `${dateParts[2]}/${dateParts[1]}` : h[0];
        return `<span class="history-tag" title="${h[0]}">${shortDate}: ${precio}</span>`;
      }).join('');
      
      const diasTxt = p.historial.length === 1 ? '1 día' : `${p.historial.length} días`;
      
      historyHtml = `
        <div class="product-history">
          <div class="history-title"><i class="bi bi-clock-history"></i> Historial: ${diasTxt}</div>
          <div class="history-tags">${historyItems}</div>
        </div>
      `;
    }
      
    card.innerHTML = `
      ${badgeHtml}
      <button class="fav-btn ${p.es_favorito ? 'is-favorite' : ''}" 
              data-id="${p.id}" 
              data-store="${p._storeId || currentStore}"
              title="Añadir a Favoritos">
        <i class="bi ${p.es_favorito ? 'bi-heart-fill' : 'bi-heart'}"></i>
      </button>
      ${imgHtml}
      <div class="product-info">
        ${p._storeName ? `<div class="product-store-tag">${p._storeName}</div>` : ''}
        <div class="product-brand">${p.marca || 'GENÉRICO'}</div>
        <div class="product-name" title="${p.nombre}">${p.nombre}</div>
        <div class="product-price-box">
          ${p.precio_normal && p.precio_normal !== p.precio_oferta ? `<div class="price-normal">${formatPrice(p.precio_normal)}</div>` : '<div>&nbsp;</div>'}
          <div class="price-offer">
             ${formatPrice(p.precio_oferta || p.precio_normal)}
          </div>
        </div>
        ${historyHtml}
        <div class="product-action">
          <a href="${p.url}" target="_blank" rel="noopener noreferrer" class="btn-view">Ver en tienda</a>
        </div>
      </div>
    `;
    productsGrid.appendChild(card);
    
    // Attach event listener to fav btn
    const favBtn = card.querySelector('.fav-btn');
    favBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const storeId = favBtn.getAttribute('data-store');
      const pId = favBtn.getAttribute('data-id');
      const isFav = favBtn.classList.contains('is-favorite');
      toggleFavorite(storeId, pId, isFav, favBtn);
    });
  });
  
  renderPagination();
}

function renderPagination() {
  const totalPages = Math.ceil(filteredProducts.length / itemsPerPage);
  
  if (totalPages <= 1) {
    pagination.classList.add('hidden');
    return;
  }
  
  pagination.classList.remove('hidden');
  pagination.innerHTML = '';
  
  const prevBtn = document.createElement('button');
  prevBtn.className = 'page-btn';
  prevBtn.disabled = currentPage === 1;
  prevBtn.innerHTML = '<i class="bi bi-chevron-left"></i>';
  prevBtn.onclick = () => { currentPage--; renderProducts(); window.scrollTo(0, 0); };
  
  const info = document.createElement('span');
  info.className = 'page-info';
  info.textContent = `Página ${currentPage} de ${totalPages}`;
  
  const nextBtn = document.createElement('button');
  nextBtn.className = 'page-btn';
  nextBtn.disabled = currentPage === totalPages;
  nextBtn.innerHTML = '<i class="bi bi-chevron-right"></i>';
  nextBtn.onclick = () => { currentPage++; renderProducts(); window.scrollTo(0, 0); };
  
  pagination.appendChild(prevBtn);
  pagination.appendChild(info);
  pagination.appendChild(nextBtn);
}

// Events
let searchTimeout = null;
searchInput.addEventListener('input', () => {
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => {
    if (currentStore) {
      applyFiltersAndSort();
    } else {
      globalSearch(searchInput.value);
    }
  }, 300);
});

inicioBtn.addEventListener('click', goHome);

sortSelect.addEventListener('change', () => {
  if (currentStore || currentProducts.length > 0) applyFiltersAndSort();
});

realDiscountToggle.addEventListener('click', () => {
  onlyRealDiscount = !onlyRealDiscount;
  // Mutuamente excluyente: apagar el otro si se activa este
  if (onlyRealDiscount) {
    onlyBestPrice = false;
    bestPriceToggle.classList.remove('active');
  }
  realDiscountToggle.classList.toggle('active', onlyRealDiscount);
  if (currentStore || currentProducts.length > 0) applyFiltersAndSort();
});

bestPriceToggle.addEventListener('click', () => {
  onlyBestPrice = !onlyBestPrice;
  // Mutuamente excluyente: apagar el otro si se activa este
  if (onlyBestPrice) {
    onlyRealDiscount = false;
    realDiscountToggle.classList.remove('active');
  }
  bestPriceToggle.classList.toggle('active', onlyBestPrice);
  if (currentStore || currentProducts.length > 0) applyFiltersAndSort();
});

// Mobile sidebar + overlay
const sidebar = document.getElementById('sidebar');
const sidebarOverlay = document.getElementById('sidebarOverlay');

function openSidebar() {
  sidebar.classList.add('open');
  sidebarOverlay.classList.add('visible');
}

function closeSidebar() {
  sidebar.classList.remove('open');
  sidebarOverlay.classList.remove('visible');
}

document.getElementById('mobile-menu-btn').addEventListener('click', () => {
  const isOpen = sidebar.classList.contains('open');
  isOpen ? closeSidebar() : openSidebar();
});

sidebarOverlay.addEventListener('click', closeSidebar);


// Initialize
initTheme();
loadData();
