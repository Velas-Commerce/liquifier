# Liquifier

The Liquifier is a Python script designed to keep LND Bitcoin Lightning nodes able to receive payments by ensuring remote liquidity is always available. Its primary uses are for e-commerce, in-person retail and payment processor nodes - basically, any node that is focused on receiving payments.

Liquidity is provided by automatically sending payouts to a specified LNURLp address. This could be an address obtained from Wallet of Satoshi, Breez, LNBits, Phoenix, etc. By doing so, your node is always ready to receive payments, keeping the bitcoin flowing into your business and into your wallet!

Please note that Liquifier script available here is designed for manual operation. While automation is possible and envisaged, it requires careful commissioning on a case-by-case basis.

**Always test on Testnet prior to running this script!**  

If you have doubts about setting up Lightning for Testnet, contact us. If you are new to Lightning automations we invite you to reach out to us for support at [velascommerce.com](https://www.velascommerce.com/)

For a complete list of compatible wallets, visit the excellent list [here](https://coincharge.io/en/lnurl-for-lightning-wallets/).

Hecho con ❤️ y ⚡ en Puerto Rico 🏝️

## Table of Contents
1. [Installation](#installation)
2. [Usage](#usage)
3. [Contributing](#contributing)
4. [License](#license)
5. [Contact Information](#contact-information)

## Installation

Follow these steps to install Liquifier.  Setting up the gRPC client for LND follows this great guide [here](https://github.com/lightningnetwork/lnd/blob/master/docs/grpc/python.md#how-to-write-a-python-grpc-client-for-the-lightning-network-daemon) which can also be used for reference.

Start by cloning our repo

```bash
$  git clone https://github.com/Velas-Commerce/liquifier
```

Note: These steps assume that you have `virtualenv` and `pip` installed on your system. If not, please follow these guides to install and set them up:

- For `pip`, follow the instructions in the [Python Packaging User Guide](https://packaging.python.org/tutorials/installing-packages/#ensure-pip-setuptools-and-wheel-are-up-to-date).
- For `virtualenv`, check out the [Virtualenv documentation](https://virtualenv.pypa.io/en/stable/installation.html).


1. Create a virtual environment for your project:

    ```shell
    $ virtualenv lnd
    ```

2. Activate the virtual environment:

    ```shell
    $ source lnd/bin/activate
    ```

3. Install dependencies (`googleapis-common-protos` is required due to the use of `google/api/annotations.proto`):

    ```shell
    lnd $ pip install grpcio grpcio-tools googleapis-common-protos
    ```

4. Clone the Google APIs repository (required due to the use of `google/api/annotations.proto`):

    ```shell
    lnd $ git clone https://github.com/googleapis/googleapis.git
    ```

5. Copy the LND `lightning.proto` file (you'll find this at `lnrpc/lightning.proto`) or just download it:

    ```shell
    lnd $ curl -o lightning.proto -s https://raw.githubusercontent.com/lightningnetwork/lnd/master/lnrpc/lightning.proto
    ```

6. Compile the proto file:

    ```shell
    lnd $ python -m grpc_tools.protoc --proto_path=googleapis:. --python_out=. --grpc_python_out=. lightning.proto
    ```
### Generating RPC Modules for Subservers

We also need to generate the RPC modules for the Router subserver (located/defined in `routerrpc/router.proto`). To do this, follow these steps:

```bash
lnd $  curl -o router.proto -s https://raw.githubusercontent.com/lightningnetwork/lnd/master/lnrpc/routerrpc/router.proto
lnd $  python -m grpc_tools.protoc --proto_path=googleapis:. --python_out=. --grpc_python_out=. router.proto
```

### Installing Additional Dependencies

With the gRPC and protobuf setup out of the way, you can now install the other Python dependencies required by our script. 

This is where the `requirements.txt` file comes in handy. To install these dependencies, first activate your virtual environment (we called this lnd)

```bash 
$ source lnd/bin/activate
```

then run:

```bash
lnd $  pip install -r requirements.txt
```
### Add Environment Variables

Create a .env file in your main directory with the following parameters.  Note that all parameters are mandatory and required for the correct functioning of the script:
```bash
# lnd environment variables
TLS_CERT_PATH=[ADD PATH TO TLS CERT]
MACAROON_PATH=[ADD PATH TO MACAROON]
# payment and balancing variables
MAXIMUM_PAYMENT_AMOUNT=[ADD MAX PAYOUT AMOUNT FOR SINGLE PAYMENT SIZE, 1000000 SATS SUGGESTED]
PREFERRED_LOCAL_BALANCE_RATIO=[ADD MIN LOCAL BALANCE RATIO FOR ELIGIBLE CHANNELS, 0.1 MIN SUGGESTED]
TIMEOUT_SEC=[ENTER TIME IN SECONDS AFTER WHICH ATTEMPTS TO PAY WILL TIMEOUT]
MAX_RETRIES=[ENTER MAX TIMES FAILED PAYMENTS SHOULD BE RETRIED, 3 SUGGESTED]
# LNURLp link for generating bolt11 invoices
LNURL_LINK=[ ADD LNURLp LINK, for example: LNURL...S9CY
```

Adding a long timeout time will cause the script to run slowly if channel partners don't respond quickly or channel partners have many unbalanced channels.  I recommend setting this based on your experience running the node, however 60 seconds is the default for lncli and may be a good starting place.

Max retries will also cause the script to run slowly in the same conditions.  Suggested value is 3.

## Usage
1. Activate your lnd virtual environment:

    ```bash
    $ source lnd/bin/activate
    ```

2. Run the Liquifier script by using the following command:

    ```bash
    lnd $ python liquifier.py
    ```

3. After running the script, you will be prompted to enter the preferred date range. This date range is used to calculate the amounts to payout. The time period is considered from 00:00 hrs to 00:00 hrs based on the server's local time.

4. The script will then calculate the required payouts and generate a list of eligible channels. After these calculations, you will be prompted to approve each payout before it's processed.

5. For record-keeping purposes, the script maintains a log file and a CSV file. The log file captures all events and transactions, while the CSV file keeps track of total payments received and each successful payout.

Note: It's recommended to monitor the log and CSV files regularly to understand the state of the payouts and to troubleshoot potential issues. 

⚡Enjoy balancing your Lightning Network node with Liquifier!⚡

## Contributing

This project was developed by Erik Alvarez and George Gbenle. We appreciate any feedback, contributions, and suggestions to improve this project and make it more useful to the community. 

To contribute:

1. Fork the repository.
2. Create a new branch for each feature or improvement.
3. Send a pull request from each feature branch to the develop branch.

Please, make sure to follow our coding style and to add unit tests for the features you add. 

Thank you for helping us to improve Liquifier!

## Contact Information
For any inquiries or further information, please feel free to reach out:

- Email: [erik@velascommerce.com](mailto:erik@velascommerce.com)
- Website: [www.velascommerce.com](https://www.velascommerce.com)
- Twitter: [@VelasCommerce](https://twitter.com/VelasCommerce)
- NOSTR: npub1mfpdevu5dsuclurfns4t3ypah8uwje73dcyycfuenxhpnq9997jqp7nesj