import jwt


_key_client = jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs")


def verify_google_identity(token, audience):
	"""Verify an id_token provided by Google, excluding the expiration claim.

	This is a function that replicates all of the checks for validity of a google
	id JSON Web Token, except for the expiration. It does check:
	* The token was issued by Google
	* The token's audience is what we specified (our Client ID)
	* The signature is valid and verifies against Google's public keys
	* The expected claims are present, including an email address

	However, it does not check the expiration. Token expiration is broadly an
	arbitrary choice made by Google, it doesn't affect us because we aren't presenting
	the token to Google at any point. So we can get persistent login by simply
	accepting expired tokens.
	"""
	if not audience:
		raise ValueError("Google client ID is required")
	key = _key_client.get_signing_key_from_jwt(token)
	claims = jwt.decode(
		token,
		key.key,
		algorithms=["RS256"],
		audience=audience,
		issuer=["accounts.google.com", "https://accounts.google.com"],
		options={
			"verify_exp": False,
			"require": ["exp", "iat", "iss", "aud", "email"],
		},
	)
	if not isinstance(claims['email'], str) or not claims['email']:
		raise ValueError("Malformed ID token, missing 'email' claim.")
	return claims
