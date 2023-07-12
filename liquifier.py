import lightning_pb2 as ln
import lightning_pb2_grpc as lnrpc
import router_pb2 as routerrpc
import router_pb2_grpc as routerstub
import codecs
import grpc
import os
import logging
from dotenv import load_dotenv, find_dotenv
import datetime
import time
import sys
import csv
from tabulate import tabulate
import requests
from lnurl import Lnurl, LnurlResponse, LnurlPayResponse

# Configure logging
logging.basicConfig(filename='log-grpc-v-liquifier.log', level=logging.DEBUG,
                    format='%(asctime)s - %(message)s')

# Load environment variables from .env file
load_dotenv(find_dotenv())

# Get the path to the tls.cert and admin.macaroon files from environment variables
tls_cert_path = os.path.expanduser(os.getenv('TLS_CERT_PATH'))
macaroon_path = os.path.expanduser(os.getenv('MACAROON_PATH'))

# Get environment variables to configure payments
maximum_payment_amount = int(os.environ['MAXIMUM_PAYMENT_AMOUNT'])
PREFERRED_LOCAL_BALANCE_RATIO = float(os.getenv('PREFERRED_LOCAL_BALANCE_RATIO', '0'))
timeout_seconds = int(os.getenv('TIMEOUT_SEC', '60'))
max_retries = int(os.getenv('MAX_RETRIES', 3))

# Due to updated ECDSA generated tls.cert we need to let gprc know that
# we need to use that cipher suite otherwise there will be a handhsake
# error when we communicate with the lnd rpc server.
os.environ["GRPC_SSL_CIPHER_SUITES"] = 'HIGH+ECDSA'

# Load the Lnd cert
cert = open(tls_cert_path, 'rb').read()
creds = grpc.ssl_channel_credentials(cert)

# Load the macaroon file
with open(macaroon_path, 'rb') as f:
    macaroon_bytes = f.read()
    macaroon = codecs.encode(macaroon_bytes, 'hex')

# Add the macaroon to the metadata
def metadata_callback(context, callback):
    callback([('macaroon', macaroon)], None)

# Create a secure channel with the macaroon
auth_creds = grpc.metadata_call_credentials(metadata_callback)
combined_creds = grpc.composite_channel_credentials(creds, auth_creds)

channel = grpc.secure_channel('localhost:10009', combined_creds)

lightning_stub = lnrpc.LightningStub(channel)
router_stub = routerstub.RouterStub(channel)

def get_date_input(prompt, start_date=None):
    while True:
        date_string = input(prompt)
        try:
            date = datetime.datetime.strptime(date_string, '%Y-%m-%d')

            # If the start_date is provided and this date is not after it, raise a ValueError
            if start_date and date <= start_date:
                raise ValueError("End date must be after start date.")

            # If the date string is valid, we can return it
            return date_string
        except ValueError as e:
            print(e)

def convert_to_unix_time(date_string):
    # Convert string to datetime object
    date = datetime.datetime.strptime(date_string, '%Y-%m-%d')

    # Convert datetime object to unix timestamp
    unix_time = int(time.mktime(date.timetuple()))

    return unix_time

def get_invoices(start_date_unix, end_date_unix):
    # Get the invoices for the specified date range
    request = ln.ListInvoiceRequest(
        creation_date_start=start_date_unix,
        creation_date_end=end_date_unix,

    )
    response = lightning_stub.ListInvoices(request)
    return response

def write_payments_received_to_csv(payments, filename=None):
    # Ensure the 'csv' directory exists
    os.makedirs('csv', exist_ok=True)

    # Create a unique filename if none was provided
    if filename is None:
        epoch_time = int(time.time())  # Get the current Unix time
        filename = f'csv/payments_received_{epoch_time}.csv'

    with open(filename, 'w', newline='') as csvfile:
        fieldnames = ['Payment Number', 'Payment Value (Sat)']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for i, payment in enumerate(payments, 1):
            writer.writerow({'Payment Number': i, 'Payment Value (Sat)': payment})

def split_into_payments(sum_amount_paid_sat, maximum_payment_amount):
    if sum_amount_paid_sat == 0:  # If no payments were made
        return []

    # Calculate number of payments
    num_payments = sum_amount_paid_sat // maximum_payment_amount
    if sum_amount_paid_sat % maximum_payment_amount != 0:
        num_payments += 1

    # Calculate the value of most payments
    payment_value = sum_amount_paid_sat // num_payments

    # Create a list of payments
    payments = [payment_value] * num_payments

    # Add any remainder to the last payment
    remainder = sum_amount_paid_sat % num_payments
    payments[-1] += remainder

    return payments

def sum_payments(invoices_response, maximum_payment_amount):
    # Extract the necessary data from the invoices
    invoices_data = []
    for invoice in invoices_response.invoices:
        if invoice.state == ln.Invoice.SETTLED:  # Only consider settled invoices
            creation_date = datetime.datetime.fromtimestamp(invoice.creation_date)
            amount_paid_sat = invoice.amt_paid_sat
            r_hash = codecs.encode(invoice.r_hash, 'hex').decode()
            invoices_data.append([creation_date, amount_paid_sat, r_hash])

    # Print the data in a tabular format
    print(tabulate(invoices_data, headers=['Creation Date', 'Amount Paid (Sat)', 'R Hash']))

    # Calculate the total sum of payments
    sum_amount_paid_sat = sum([invoice[1] for invoice in invoices_data])
    logging.info(f"Total amount paid (sat): {sum_amount_paid_sat}")  # Log the total amount paid
    print(f"\nTotal amount paid (sat): {sum_amount_paid_sat}\n")

    # Split the total sum into payments
    payments = split_into_payments(sum_amount_paid_sat, maximum_payment_amount)
    assert sum(payments) == sum_amount_paid_sat, "Sum of payments does not match total invoice amount!"

    # Prepare payment data for tabular display
    payments_data = [[i+1, payment] for i, payment in enumerate(payments)]

    # Print the payments data in a tabular format
    print(tabulate(payments_data, headers=['Payment Number', 'Payment Value (Sat)']))
    print(f"\nTotal amount calculated for payments (sat): {sum(payments)}\n")

    # Write the payments data to a CSV file
    write_payments_received_to_csv(payments)

    return payments

def find_and_order_channels(payment, lightning_stub):
    # Get the list of channels from the GRPC service
    list_channels_request = ln.ListChannelsRequest(
        active_only=True,
    )
    list_channels_response = lightning_stub.ListChannels(list_channels_request)

    # List to store eligible channels
    eligible_channels = []

    # Dictionaries to store local balances and local balance ratios
    local_balances = {}
    local_balance_ratios = {}

    for channel in list_channels_response.channels:
        # Extract the channel ID, capacity, local balance, and active status
        chan_id = channel.chan_id  # Adjusted to chan_id
        capacity = channel.capacity
        local_balance = channel.local_balance
        active = channel.active

        # If local_balance is greater than or equal to the payment, append it to eligible_channels
        if local_balance >= payment and active:
            # Calculate the local_balance_ratio
            local_balance_ratio = local_balance / capacity

            # Only add the channel to eligible_channels if local_balance_ratio is greater than PREFERRED_LOCAL_BALANCE_RATIO
            if local_balance_ratio > PREFERRED_LOCAL_BALANCE_RATIO:
                eligible_channels.append({
                    'channel_id': chan_id,
                    'local_balance_ratio': local_balance_ratio,
                    'local_balance': local_balance,
                    'capacity': capacity,
                    'active': active
                })

                # Update local_balances and local_balance_ratios
                local_balances[chan_id] = {'balance': local_balance, 'capacity': capacity}
                local_balance_ratios[chan_id] = local_balance_ratio

    # Sort eligible_channels by local_balance_ratio in descending order
    eligible_channels.sort(key=lambda x: x['local_balance_ratio'], reverse=True)

    # Print the eligible channels in a tabular format
    print(tabulate(eligible_channels, headers="keys"))

    return eligible_channels, local_balances, local_balance_ratios

def lnurlp_bolt11_invoice_generator(payout_amount):
    # Get the lnurl link from the environment variable
    lnurl_link = os.getenv('LNURL_LINK')

    if lnurl_link is None:
        raise Exception('Please set the LNURL_LINK environment variable')

    # Probe the lnurl link to get its parameters
    lnurl = Lnurl(lnurl_link)
    r = requests.get(lnurl.url)

    if r.status_code != 200:
        raise Exception(f'Error contacting the lnurl service. Response: {r.text}')

    res = LnurlResponse.from_dict(r.json())

    if not isinstance(res, LnurlPayResponse):
        raise Exception('This is not a valid lnurl-pay link')

    # Convert min and max sendable amounts to satoshis
    min_amount_sats = res.min_sendable // 1000
    max_amount_sats = res.max_sendable // 1000

    # Calculate the payout_amount in millisats
    payout_amount_msat = payout_amount * 1000

    # Create a payment request
    r = requests.get(res.callback, params={'amount': payout_amount_msat})

    timeout = 5  # Define your timeout value here

    if r.status_code != 200 and 'Request throttled' in r.text:  # Check if request is being throttled
        print("Request throttled. Waiting 5 seconds before retrying...")
        time.sleep(5)  # Wait for 5 seconds
        r = requests.get(res.callback, params={"amount": payout_amount_msat}, timeout=timeout)  # Retry request
        if r.status_code != 200:  # Check if second attempt also fails
            raise Exception(f'Error creating payment request after retry. Response: {r.text}')
    elif r.status_code != 200:
        raise Exception(f'Error creating payment request. Response: {r.text}')

    payment_request = r.json()

    # Return the payment request to be paid by a lightning wallet
    return payment_request

def generate_invoice_for_payment(payment):
    # Generate an invoice for a single payment
    invoice = lnurlp_bolt11_invoice_generator(payment)
    return invoice['pr']

# Define the status and failure reasons mappings
status_mapping = {
    0: "UNKNOWN",
    1: "IN_FLIGHT",
    2: "SUCCEEDED",
    3: "FAILED"
}

failure_reason_mapping = {
    0: "FAILURE_REASON_NONE",
    1: "FAILURE_REASON_TIMEOUT",
    2: "FAILURE_REASON_NO_ROUTE",
    3: "FAILURE_REASON_ERROR",
    4: "FAILURE_REASON_INCORRECT_PAYMENT_DETAILS",
    5: "FAILURE_REASON_INSUFFICIENT_BALANCE"
}

def send_payment(invoice, timeout_seconds, outgoing_chan_id, router_stub, max_retries):
    for attempt in range(max_retries):
        print(f"Attempting to pay invoice through channel ID: {outgoing_chan_id} (attempt {attempt + 1})")

        request = routerrpc.SendPaymentRequest(
            payment_request=invoice,  # the invoice string
            timeout_seconds=timeout_seconds,  # the number of seconds before the payment attempt times out
            outgoing_chan_id=outgoing_chan_id,  # the channel id to use for sending the payment
        )
        for response in router_stub.SendPaymentV2(request):
            # Map the integer response status and failure reason to their corresponding messages
            response_status = status_mapping.get(response.status, "UNKNOWN STATUS")
            response_failure_reason = failure_reason_mapping.get(response.failure_reason, "UNKNOWN FAILURE REASON")

            print(f"Payment request: {response.payment_request}")
            print(f"Status: {response_status}")
            print(f"Failure reason: {response_failure_reason}")
            print(f"Value (sat): {response.value_sat}")

            # If payment has succeeded, return True
            if response.status == 2:  # 'SUCCEEDED' corresponds to the integer value 2
                print("Payment sent successfully through channel ID:", outgoing_chan_id)
                return True

            # If payment has failed due to "FAILURE_REASON_TIMEOUT", retry
            elif response.status == 3:  # 'FAILED' corresponds to the integer value 3
                if response.failure_reason == 1:  # 'FAILURE_REASON_TIMEOUT' corresponds to the integer value 1
                    print(f"Payment attempt {attempt + 1} failed due to timeout. Retrying...")
                    time.sleep(5)  # This will pause execution for 5 seconds before the next attempt
                else:
                    print(f"Payment attempt {attempt + 1} failed due to {response_failure_reason}. Exiting...")
                    return False

    # If we've exhausted all retries and payment still fails, return False
    print(f"All attempts exhausted. Payment could not be sent through channel ID: {outgoing_chan_id}.")
    return False

def retry_payments(payments, timeout_seconds, eligible_channels, router_stub, max_retries):
    successful_payments = []  # List to store the successful payments

    for payment in payments:
        invoice = generate_invoice_for_payment(payment)  # Generate a new invoice for the payment
        success_flag = False  # Flag to track whether a payment was successful

        for chan_id in eligible_channels:
            if confirm_payout(payment, chan_id):  # Call to the confirmation function
                if send_payment(invoice, timeout_seconds, chan_id, router_stub, max_retries):
                    successful_payments.append({"Payment": payment, "Channel ID": chan_id})
                    success_flag = True  # Payment was successful, so update the flag
                    break  # Break the loop and move on to the next payment
                else:
                    print(f"Payment failed. Trying next eligible channel...")
            else:
                return  # If user does not confirm, return and stop retrying payments.

        if not success_flag:  # If no successful payment was made, exit the loop
            break

    total_payments_amount = sum(payment for payment in payments)
    successful_payments_amount = sum(payment["Payment"] for payment in successful_payments)

    if successful_payments:
        print("\nSuccessful payments:")
        print(tabulate(successful_payments, headers="keys"))
        print(f"\nPaid out {successful_payments_amount} of {total_payments_amount} total.")
    else:
        print("No payments could be processed successfully.")

    # Write the successful payments to a CSV file
    write_successful_payouts_to_csv(successful_payments)

    return True

def confirm_payout(payment_amount, channel_id):
    while True:
        user_input = input(f"Attempt to send payout of {payment_amount} through channel {channel_id}? "
                           "Enter y to continue or n to exit program: ").lower()
        if user_input == 'y':
            return True
        elif user_input == 'n':
            print("User cancelled the payout. Exiting script...")
            logging.info("User cancelled the payout. Exiting script...")
            sys.exit()
        else:
            print("Invalid input. Please enter either 'y' or 'n'.")

def write_successful_payouts_to_csv(successful_payments, filename=None):
    # Ensure the 'csv' directory exists
    os.makedirs('csv', exist_ok=True)

    # Create a unique filename if none was provided
    if filename is None:
        epoch_time = int(time.time())  # Get the current Unix time
        filename = f'csv/successful_payouts_{epoch_time}.csv'

    with open(filename, 'w', newline='') as csvfile:
        fieldnames = ['Payment', 'Channel ID']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for payment in successful_payments:
            writer.writerow(payment)

def main():
    try:
        logging.info("Script started")

        # Retrieve and display the wallet balance
        response = lightning_stub.WalletBalance(ln.WalletBalanceRequest())
        print(response.total_balance)

        # Ask the user for the start date
        start_date_string = get_date_input("Enter the start date (YYYY-MM-DD): ")

        # Convert start_date_string to a datetime object
        start_date = datetime.datetime.strptime(start_date_string, '%Y-%m-%d')

        # Ask the user for the end date with the start date as a reference
        end_date_string = get_date_input("Enter the end date (YYYY-MM-DD): ", start_date)

        # Convert the dates to unix time
        start_date_unix = convert_to_unix_time(start_date_string)
        end_date_unix = convert_to_unix_time(end_date_string)

        # Get the invoices for the specified date range
        invoices_response = get_invoices(start_date_unix, end_date_unix)

        # Call the sum_payments function
        payments = sum_payments(invoices_response, maximum_payment_amount)

        # Exit the script if no payments are found in the specified date range
        if sum(payments) == 0:
            print("No payments received during the specified time range. Exiting script...")
            logging.info("No payments received during the specified time range. Exiting script...")
            sys.exit()

        # Call the find_and_order_channels function
        eligible_channels, local_balances, local_balance_ratios = find_and_order_channels(payments[0], lightning_stub)

        # Make a list of eligible channel IDs
        eligible_channel_ids = [channel['channel_id'] for channel in eligible_channels]

        # Try to send each payment through all eligible channels
        if eligible_channel_ids:  # check if there are any eligible channels
            retry_payments(payments, timeout_seconds, eligible_channel_ids, router_stub, max_retries)
        else:
            print("No eligible channels to make the payment")

    except Exception as e:
        logging.error(f"Script ended due to an error: {e}")
        raise  # re-raises the last exception

    else:
        logging.info("Script finished")

if __name__ == '__main__':
    main()