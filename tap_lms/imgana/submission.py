import frappe
import json
import pika

# Define the RabbitMQ configuration directly in the code
rabbitmq_config = {
    'host': 'armadillo.rmq.cloudamqp.com',
    'port': 5672,
    'virtual_host': 'fzdqidte',
    'username': 'fzdqidte',
    'password': '0SMrDogBVcWUcu9brWwp2QhET_kArl59',
    'queue': 'submission_queue'
}

@frappe.whitelist(allow_guest=True)
def submit_artwork(api_key, assign_id, student_id, img_url):
    # Authenticate the API request using the provided api_key
    api_key_doc = frappe.db.get_value("API Key", {"key": api_key, "enabled": 1}, ["user"], as_dict=True)
    if not api_key_doc:
        frappe.throw("Invalid API key")

    # Switch to the user associated with the API key
    frappe.set_user(api_key_doc.user)

    try:
        # Create a new submission
        submission = frappe.new_doc("ImgSubmission")
        submission.assign_id = assign_id
        submission.student_id = student_id
        submission.img_url = img_url
        submission.status = "Pending"
        submission.insert()
        frappe.db.commit()

        # Log for debugging
        frappe.logger("submission").debug(f"Inserted submission: assign_id={submission.assign_id}, student_id={submission.student_id}, img_url={submission.img_url}")

        # Send the submission details to RabbitMQ
        enqueue_submission(submission.name)

        return {"message": "Submission received", "submission_id": submission.name}

    finally:
        # Switch back to the original user
        frappe.set_user("Administrator")

def enqueue_submission(submission_id):
    submission = frappe.get_doc("ImgSubmission", submission_id)
    payload = {
        "submission_id": submission.name,
        "assign_id": submission.assign_id,
        "student_id": submission.student_id,
        "img_url": submission.img_url
    }

    # Establish a connection to RabbitMQ
    credentials = pika.PlainCredentials(rabbitmq_config['username'], rabbitmq_config['password'])
    parameters = pika.ConnectionParameters(
        rabbitmq_config['host'],
        rabbitmq_config['port'],
        rabbitmq_config['virtual_host'],
        credentials
    )
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()

    # Declare the queue
    channel.queue_declare(queue=rabbitmq_config['queue'])

    # Publish the message to the queue
    channel.basic_publish(
        exchange='',
        routing_key=rabbitmq_config['queue'],
        body=json.dumps(payload)
    )

    # Close the connection
    connection.close()