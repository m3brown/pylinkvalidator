"""
Contains the reporting functions
"""
from __future__ import unicode_literals, absolute_import, print_function

import codecs
import json
import re
import smtplib
import sys

from email.mime.text import MIMEText

from junit_xml import TestSuite, TestCase

from pylinkvalidator.compat import StringIO
from pylinkvalidator.models import (
    FORMAT_JSON,
    FORMAT_JUNIT,
    FORMAT_PLAIN,
    REPORT_TYPE_ALL,
    REPORT_TYPE_ERRORS,
)


PLAIN_TEXT = "text/plain"
HTML = "text/html"

WHITESPACES = re.compile(r"\s+")


EMAIL_HEADER = "from: {0}\r\nsubject: {1}\r\nto: {2}\r\nmime-version: 1.0\r\n"\
               "content-type: {3}\r\n\r\n{4}"


def close_quietly(a_file):
    """Closes a file and does not report an error."""
    try:
        if a_file:
            a_file.close()
    except Exception:
        pass


def report(site, config, total_time, logger=None):
    """Prints reports to console, file, and email."""
    output_files = []
    output_file = None
    email_file = None

    if config.options.output:
        output_file = codecs.open(config.options.output, "w", "utf-8")
        output_files.append(output_file)

    if config.options.smtp:
        email_file = StringIO()
        output_files.append(email_file)

    if config.options.console or not output_files:
        output_files.append(sys.stdout)

    try:
        if config.options.format == FORMAT_PLAIN:
            _write_plain_text_report(site, config, output_files, total_time)
        if config.options.format == FORMAT_JSON:
            _write_json_report(site, config, output_file, total_time)
        if config.options.format == FORMAT_JUNIT:
            _write_junit_report(site, config, output_file, total_time)
    except Exception:
        if logger:
            logger.exception("An exception occurred while writing the report")

    if output_file:
        close_quietly(output_file)

    if email_file:
        send_email(email_file, site, config)


def _write_plain_text_report(site, config, output_files, total_time):
    if config.options.multi:
        _write_plain_text_report_multi(site, config, output_files, total_time)
    else:
        _write_plain_text_report_single(site, config, output_files, total_time)


def _write_junit_report(site, config, output_file, total_time):
    pages = site.pages
    test_cases = []

    for results, resource in pages.items():
        origins = [source.origin.geturl() for source in resource.sources]
        if resource.status == 200:
            test_case = TestCase(
                name=resource.url_split.geturl(),
                classname=results.hostname,
                elapsed_sec=resource.response_time,
                stdout=resource.status,
                status="passed"
                )
        else:
            stderr_message = "Link found on:\n{}".format("\n".join(origins))
            test_case = TestCase(
                name=resource.url_split.geturl(),
                classname=results.hostname,
                elapsed_sec=resource.response_time,
                stderr=stderr_message,
                status="failed"
            )
            if resource.exception:
                message = str(resource.exception)
            else:
                message = "Expected 200 OK but got {}".format(resource.status)
            test_case.add_failure_info(
                message=message, failure_type="UnexpectedStatusCode")
        test_cases.append(test_case)
    test_suite = TestSuite("pylinkvalidator test suite", test_cases)
    output_file.write(TestSuite.to_xml_string([test_suite]))
    print_summary(site, config, total_time)


def _write_json_report(site, config, output_file, total_time):
    start_urls = ",".join((start_url_split.geturl() for start_url_split in
                           site.start_url_splits))

    total_urls = len(site.pages)
    total_errors = len(site.error_pages)

    if not site.is_ok:
        global_status = "ERROR"
        error_summary = "with {0} error(s) ".format(total_errors)
    else:
        global_status = "SUCCESS"
        error_summary = ""

    meta = {
        "total_urls": total_urls,
        "total_errors": total_errors,
        "total_time": total_time,
        "start_urls": start_urls,
        "global_status": global_status,
        "error_summary": error_summary
    }
    try:
        avg_response_time = site.get_average_response_time()
        avg_process_time = site.get_average_process_time()
        meta.update({"avg_response_time": avg_response_time})
        meta.update({"avg_process_time": avg_process_time})
    except Exception:
        from traceback import print_exc
        print_exc()

    pages = {}

    if config.options.report_type == REPORT_TYPE_ERRORS:
        pages = site.error_pages
    elif config.options.report_type == REPORT_TYPE_ALL:
        pages = site.pages

    res_pages = []

    for results, resource in pages.items():
        details = {
            'link': resource.url_split.geturl(),
            'fragment': results.fragment,
            'hostname': results.hostname,
            'netloc': results.netloc,
            'is_local': resource.is_local,
            'is_html': resource.is_html,
            'is_ok': resource.is_ok,
            'is_timeout': resource.is_timeout,
            'process_time': resource.process_time,
            'response_time': resource.response_time,
            'status': resource.status,
            'path': results.path,
            'port': results.port,
            'query': results.query,
            'scheme': results.scheme,
            'origins': [source.origin.geturl() for source in resource.sources],
            'sources': [source.origin_str for source in resource.sources],
            'targets': [source.target for source in resource.sources]
        }
        res_pages.append(details)

    res = {
        "meta": meta,
        "pages": res_pages
    }
    output_file.write(
            json.dumps(res, sort_keys=True, indent=4, separators=(',', ': ')))
    print_summary(site, config, total_time)


def _write_plain_text_report_multi(site, config, output_files, total_time):
    total_urls = len(site.pages)
    total_errors = len(site.error_pages)

    if not site.is_ok:
        global_status = "ERROR"
        error_summary = "with {0} error(s) ".format(total_errors)
    else:
        global_status = "SUCCESS"
        error_summary = ""

    try:
        avg_response_time = site.get_average_response_time()
        avg_process_time = site.get_average_process_time()

        oprint(
            "{0} Crawled {1} urls {2}from {4} sites in {3:.2f} seconds"
            .format(
                global_status, total_urls, error_summary, total_time,
                len(site.start_url_splits)),
            files=output_files)

        oprint("  average response time: {0:.2f} seconds".format(
            avg_response_time), files=output_files)

        oprint("  average process time: {0:.2f} seconds".format(
            avg_process_time), files=output_files)

        pages = {}

        if config.options.report_type == REPORT_TYPE_ERRORS:
            pages = site.multi_error_pages
        elif config.options.report_type == REPORT_TYPE_ALL:
            pages = site.multi_pages

        for domain, pages_dict in pages.items():
            if pages_dict:
                oprint(
                    "\n\n  Start Domain: {0}".format(domain),
                    files=output_files)

                _print_details(pages_dict.values(), output_files, config, 4)
    except Exception:
        from traceback import print_exc
        print_exc()


def _write_plain_text_report_single(site, config, output_files, total_time):
    start_urls = ",".join((start_url_split.geturl() for start_url_split in
                           site.start_url_splits))

    total_urls = len(site.pages)
    total_errors = len(site.error_pages)

    if not site.is_ok:
        global_status = "ERROR"
        error_summary = "with {0} error(s) ".format(total_errors)
    else:
        global_status = "SUCCESS"
        error_summary = ""

    try:
        avg_response_time = site.get_average_response_time()
        avg_process_time = site.get_average_process_time()

        oprint("{0} Crawled {1} urls {2}in {3:.2f} seconds".format(
            global_status, total_urls, error_summary, total_time),
            files=output_files)

        oprint("  average response time: {0:.2f} seconds".format(
            avg_response_time), files=output_files)

        oprint("  average process time: {0:.2f} seconds".format(
            avg_process_time), files=output_files)

    except Exception:
        from traceback import print_exc
        print_exc()

    pages = {}

    if config.options.report_type == REPORT_TYPE_ERRORS:
        pages = site.error_pages
    elif config.options.report_type == REPORT_TYPE_ALL:
        pages = site.pages

    if pages:
        oprint("\n  Start URL(s): {0}".format(start_urls), files=output_files)
        _print_details(pages.values(), output_files, config)


def print_summary(site, config, total_time, indent=2):
    total_urls = len(site.pages)
    total_errors = len(site.error_pages)

    if not site.is_ok:
        global_status = "ERROR"
        error_summary = "with {0} error(s) ".format(total_errors)
    else:
        global_status = "SUCCESS"
        error_summary = ""

    print("{0} Crawled {1} urls {2}in {3:.2f} seconds".format(
        global_status, total_urls, error_summary, total_time))

    pages = {}

    if config.options.report_type == REPORT_TYPE_ERRORS:
        pages = site.error_pages
    elif config.options.report_type == REPORT_TYPE_ALL:
        pages = site.pages

    initial_indent = " " * indent
    for page in pages.values():
        print("\n{2}{0}: {1}".format(
            page.get_status_message(), page.url_split.geturl(),
            initial_indent))
        for content_message in page.get_content_messages():
            print("{1}  {0}".format(content_message, initial_indent))
        for source in page.sources:
            print("{1}  from {0} target={2}".format(
                source.origin.geturl(), initial_indent, source.target))
            if config.options.show_source:
                print("{1}    {0}".format(
                    source.origin_str, initial_indent))


def _print_details(page_iterator, output_files, config, indent=2):
    initial_indent = " " * indent
    for page in page_iterator:
        oprint("\n{2}{0}: {1}".format(
            page.get_status_message(), page.url_split.geturl(),
            initial_indent),
            files=output_files)
        for content_message in page.get_content_messages():
            oprint("{1}  {0}".format(content_message, initial_indent),
                   files=output_files)
        for source in page.sources:
            oprint("{1}  from {0} target={2}".format(
                source.origin.geturl(), initial_indent, source.target), files=output_files)
            if config.options.show_source:
                oprint("{1}    {0}".format(
                    source.origin_str, initial_indent),
                       files=output_files)


def oprint(message, files):
    """Prints to a sequence of files."""
    for file in files:
        print(message, file=file)


def truncate(value, size=72):
    """Truncates a string if its length is higher than size."""
    value = value.replace("\n", " ").replace("\r", "").replace("\t", " ")
    value = value.strip()
    value = WHITESPACES.sub(" ", value)

    if len(value) > size:
        value = "{0}...".format(value[:size-3])

    return value


def send_email(email_file, site, config):
    options = config.options
    if options.subject:
        subject = options.subject
    else:
        if site.is_ok:
            subject = "SUCCESS - {0}".format(site.start_url_splits[0].geturl())
        else:
            subject = "ERROR - {0}".format(site.start_url_splits[0].geturl())

    if options.from_address:
        from_address = options.from_address
    else:
        from_address = "pylinkvalidator@localhost"

    if not options.address:
        print("Email address must be specified when using smtp.")
        sys.exit(1)

    addresses = options.address.split(",")

    msg = MIMEText(email_file.getvalue(), 'plain', "UTF-8")

    msg['From'] = from_address
    msg['To'] = ", ".join(addresses)
    msg['Subject'] = subject

    smtpserver = smtplib.SMTP(options.smtp, options.port)

    if options.tls:
        smtpserver.ehlo()
        smtpserver.starttls()
        smtpserver.ehlo

    if options.smtp_username and options.smtp_password:
        smtpserver.login(options.smtp_username, options.smtp_password)

    smtpserver.sendmail(from_address, addresses, msg.as_string())

    smtpserver.quit()
