import Keycloak from 'keycloak-js'

export const keycloak = new Keycloak({
  url: 'https://keycloak.local:8443',
  realm: 'GenAI-platform',
  clientId: 'genai-demo-web',
})

export async function initializeAuth(): Promise<boolean> {
  return keycloak.init({
    onLoad: 'check-sso',
    pkceMethod: 'S256',
    checkLoginIframe: false,
  })
}

export async function apiFetch(path: string): Promise<Response> {
  if (!keycloak.authenticated || !keycloak.token) {
    throw new Error('Authentication required')
  }
  await keycloak.updateToken(30)
  return fetch(path, { headers: { Authorization: `Bearer ${keycloak.token}` } })
}
