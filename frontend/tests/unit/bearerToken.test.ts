import { describe, expect, it } from 'vitest'
import { curlCommand, jwtClaims, userinfoUrl, whoamiUrl } from '../../src/lib/bearerToken'

const b64url = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64url')
const JWT = `${b64url({ alg: 'RS256' })}.${b64url({ iss: 'https://idp.example/', aud: ['api', 'https://idp.example/userinfo'], exp: 1794160709 })}.sig`

describe('the bearer token test helpers', () => {
  it('calls the bearer route on the API host, under the mcp mapping', () => {
    expect(whoamiUrl('https://ems-test.api.porth-dau.ems.estynsoftware.cloud/'))
      .toBe('https://ems-test.api.porth-dau.ems.estynsoftware.cloud/mcp/whoami')
  })

  it("asks the token's own issuer for userinfo", () => {
    expect(userinfoUrl('https://idp.example/')).toBe('https://idp.example/userinfo')
  })

  it('reads a JWT payload, with or without base64 padding, and nothing else', () => {
    expect(jwtClaims(JWT)).toMatchObject({ iss: 'https://idp.example/', exp: 1794160709 })
    expect(jwtClaims(`  ${JWT}\n`)).not.toBeNull()
    expect(jwtClaims('prth_opaque-token')).toBeNull()
    expect(jwtClaims('a.!!!.c')).toBeNull()
  })

  it('gives the same call as curl, with exactly the token', () => {
    expect(curlCommand('https://h/mcp/whoami', ` ${JWT} `))
      .toBe(`curl -sS -i -H 'Authorization: Bearer ${JWT}' 'https://h/mcp/whoami'`)
  })
})
