"""
.. module: lemur.plugins.lemur_verisign.verisign
    :platform: Unix
    :synopsis: This module is responsible for communicating with the VeriSign VICE 2.0 API.
    :copyright: (c) 2015 by Netflix Inc., see AUTHORS for more
    :license: Apache, see LICENSE for more details.

.. moduleauthor:: Kevin Glisson <kglisson@netflix.com>
"""
import arrow
import requests
import xmltodict

from flask import current_app

from lemur.plugins.bases import IssuerPlugin
from lemur.plugins import lemur_verisign as verisign
from lemur.plugins.lemur_verisign import constants
from lemur.common.utils import get_psuedo_random_string


# https://support.venafi.com/entries/66445046-Info-VeriSign-Error-Codes
VERISIGN_ERRORS = {
    "0x30c5": "Domain Mismatch when enrolling for an SSL certificate, a domain in your request has not been added to verisign",
    "0x482d": "Cannot issue SHA1 certificates expiring after 31/12/2016",
    "0x3a10": "Invalid X509 certificate format.: an unsupported certificate format was submitted",
    "0x4002": "Internal QM Error. : Internal Database connection error.",
    "0x3301": "Bad transaction id or parent cert not renewable.: User try to renew a certificate that is not yet ready for renew or the transaction id is wrong",
    "0x3069": "Challenge phrase mismatch: The challenge phrase submitted does not match the original one",
    "0x3111": "Unsupported Product: User submitted a wrong product or requested cipher is not supported",
    "0x30e8": "CN or org does not match the original one.: the submitted CSR contains a common name or org that does not match the original one",
    "0x1005": "Duplicate certificate: a certificate with the same common name exists already",
    "0x0194": "Incorrect Signature Algorithm: The requested signature algorithm is not supported for the key type. i.e. an ECDSA is submitted for an RSA key",
    "0x6000": "parameter missing or incorrect: This is a general error code for missing or incorrect parameters. The reason will be in the response message.  i.e. 'CSR is missing, 'Unsupported serverType' when no supported serverType could be found., 'invalid transaction id'",
    "0x3063": "Certificate not allowed: trying to issue a certificate that is not configured for the account",
    "0x23df": "No MDS Data Returned: internal connection lost or server not responding. this should be rare",
    "0x3004": "Invalid Account: The users mpki account associated with the certificate is not valid or not yet active",
    "0x4101": "Internal Error: internal server error, user should try again later. (Also check that State is spelled out",
    "0x3101": "Missing admin role: Your account does not have the admin role required to access the webservice API",
    "0x3085": "Account does not have webservice feature.: Your account does not the the webservice role required to access the webservice API",
    "0x9511": "Corrupted CSR : the submitted CSR was mal-formed",
    "0xa001": "Public key format does not match.: The public key format does not match the original cert at certificate renewal or replacement. E.g. if you try to renew or replace an RSA cert with a DSA or ECC key based CSR",
    "0x0143": "Certificate End Date Error: You are trying to replace a certificate with validity end date exceeding the original cert. or the certificate end date is not valid",
    "0x482d": "SHA1 validity check error: What error code do we get when we submit the SHA1 SSL requests with the validity more than 12/31/2016?",
    "0x482e": "What error code do we get when we cannot complete the re-authentication for domains with a newly-approved gTLD 30 days after the gTLD approval",
    "0x4824": "Per CA/B Forum baseline requirements, non-FQDN certs cannot exceed 11/1/2015. Examples: hostname, foo.cba (.cba is a pending gTLD)",
    "eE0x48": "Currently the maximum cert validity is 4-years",
    "0x4826": "OU misleading. See comments",
    "0x4827": "Org re-auth past due. EV org has to go through re-authentication every 13 months; OV org has to go through re-authentication every 39 months",
    "0x482a": "Domain re-auth past due. EV domain has to go through re-authentication every 13 months; OV domain has to go through re-authentication every 39 months.",
    "0x482b": "No org address was set to default, should not happen",
    "0x482c": "signature algorithm does not match intended key type in the CSR (e.g. CSR has an ECC key, but the signature algorithm is sha1WithRSAEncryption)",
    "0x600E": "only supports ECC keys with the named curve NIST P-256, aka secp256r1 or prime256v1, other ECC key sizes will get this error ",
    "0x6013": "only supports DSA keys with (2048, 256) as the bit lengths of the prime parameter pair (p, q), other DSA key sizes will get this error",
    "0x600d": "RSA key size < 2A048",
    "0x4828": "Verisign certificates can be at most two years in length",
    "0x3043": "Certificates must have a validity of at least 1 day",
    "0x950b": "CSR: Invalid State",
}


def process_options(options):
    """
    Processes and maps the incoming issuer options to fields/options that
    verisign understands

    :param options:
    :return: dict or valid verisign options
    """
    data = {
        'challenge': get_psuedo_random_string(),
        'serverType': 'Apache',
        'certProductType': 'Server',
        'firstName': current_app.config.get("VERISIGN_FIRST_NAME"),
        'lastName': current_app.config.get("VERISIGN_LAST_NAME"),
        'signatureAlgorithm': 'sha256WithRSAEncryption',
        'email': current_app.config.get("VERISIGN_EMAIL")
    }

    if options.get('validityEnd'):
        end_date, period = get_default_issuance(options)
        data['specificEndDate'] = end_date
        data['validityPeriod'] = period

    return data


def get_default_issuance(options):
    """
    Gets the default time range for certificates

    :param options:
    :return:
    """
    specific_end_date = arrow.get(options['validityEnd']).replace(days=-1).format("MM/DD/YYYY")

    now = arrow.utcnow()
    then = arrow.get(options['validityEnd'])

    if then < now.replace(years=+1):
        validity_period = '1Y'
    elif then < now.replace(years=+2):
        validity_period = '2Y'
    else:
        raise Exception("Verisign issued certificates cannot exceed two years in validity")

    return specific_end_date, validity_period


def handle_response(content):
    """
    Helper function for parsing responses from the Verisign API.
    :param content:
    :return: :raise Exception:
    """
    d = xmltodict.parse(content)
    global VERISIGN_ERRORS
    if d.get('Error'):
        status_code = d['Error']['StatusCode']
    elif d.get('Response'):
        status_code = d['Response']['StatusCode']
    if status_code in VERISIGN_ERRORS.keys():
        raise Exception(VERISIGN_ERRORS[status_code])
    return d


class VerisignIssuerPlugin(IssuerPlugin):
    title = 'Verisign'
    slug = 'verisign-issuer'
    description = 'Enables the creation of certificates by the VICE2.0 verisign API.'
    version = verisign.VERSION

    author = 'Kevin Glisson'
    author_url = 'https://github.com/netflix/lemur'

    def __init__(self, *args, **kwargs):
        self.session = requests.Session()
        self.session.cert = current_app.config.get('VERISIGN_PEM_PATH')
        super(VerisignIssuerPlugin, self).__init__(*args, **kwargs)

    def create_certificate(self, csr, issuer_options):
        """
        Creates a Verisign certificate.

        :param csr:
        :param issuer_options:
        :return: :raise Exception:
        """
        url = current_app.config.get("VERISIGN_URL") + '/enroll'

        data = process_options(issuer_options)
        data['csr'] = csr

        current_app.logger.info("Requesting a new verisign certificate: {0}".format(data))

        response = self.session.post(url, data=data)
        cert = handle_response(response.content)['Response']['Certificate']
        return cert, constants.VERISIGN_INTERMEDIATE,

    @staticmethod
    def create_authority(options):
        """
        Creates an authority, this authority is then used by Lemur to allow a user
        to specify which Certificate Authority they want to sign their certificate.

        :param options:
        :return:
        """
        role = {'username': '', 'password': '', 'name': 'verisign'}
        return constants.VERISIGN_ROOT, "", [role]

    def get_available_units(self):
        """
        Uses the Verisign to fetch the number of available unit's left. This can be used to get tabs
        on the number of certificates that can be issued.

        :return:
        """
        url = current_app.config.get("VERISIGN_URL") + '/getTokens'
        response = self.session.post(url, headers={'content-type': 'application/x-www-form-urlencoded'})
        return handle_response(response.content)['Response']['Order']
