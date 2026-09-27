const API_BASE = ''; 

export function setToken(token) {
  localStorage.setItem('token', token);
}
export function getToken() {
  return localStorage.getItem('token');
}
export function removeToken() {
  localStorage.removeItem('token');
  localStorage.removeItem('user');
}
export function getUser() {
  const userStr = localStorage.getItem('user');
  return userStr ? JSON.parse(userStr) : null;
}
export function setUser(user) {
  localStorage.setItem('user', JSON.stringify(user));
}
export function isAuthenticated() {
  return !!getToken();
}
export function isAdmin() {
  const user = getUser();
  return user && user.role === 'admin';
}

export async function apiFetch(endpoint, options = {}) {
  const token = getToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token && { 'Authorization': `Bearer ${token}` }),
    ...options.headers,
  };
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });
  if (response.status === 401) {
    removeToken();
    window.location.href = '/login.html';
    return null;
  }
  return response;
}