#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <getopt.h>
#include <arpa/inet.h>
#include <time.h>
#include <rdma/rdma_cma.h>

#define MAX_POLLS   10000
#define POLL_SLEEP_US 0

enum mode { MODE_POLL, MODE_EVENT, MODE_HYBRID };

void usage(const char *prog) {
    fprintf(stderr, "Usage: %s [--mode <poll|event|hybrid>] <server_ip>\n", prog);
    exit(1);
}

// ------------------- Polling Mode -------------------
int wait_polling(struct ibv_cq *cq, char *buf, size_t buf_size) {
    struct ibv_wc wc;
    int ne = 0;
    while (ne == 0) {
        ne = ibv_poll_cq(cq, 1, &wc);
    }
    if (wc.status == IBV_WC_SUCCESS) {
        printf("[Polling Mode] Data sent successfully\n");
        return 0;
    } else {
        printf("[Polling Mode] Send failed, status=%d\n", wc.status);
        return -1;
    }
}

// ------------------- Event-Driven Mode -------------------
int wait_event(struct ibv_cq *cq, char *buf, size_t buf_size, struct ibv_comp_channel *channel) {
    struct ibv_wc wc;
    int ne;
    ibv_req_notify_cq(cq, 0);
    ne = ibv_poll_cq(cq, 1, &wc);
    if (ne == 0) {
        struct ibv_cq *ev_cq;
        void *ev_ctx;
        if (ibv_get_cq_event(channel, &ev_cq, &ev_ctx)) {
            perror("ibv_get_cq_event");
            return -1;
        }
        ibv_ack_cq_events(cq, 1);
        ne = ibv_poll_cq(cq, 1, &wc);
    }
    if (ne > 0 && wc.status == IBV_WC_SUCCESS) {
        printf("[Event-Driven] Data sent successfully\n");
        return 0;
    } else if (ne > 0) {
        printf("[Event-Driven] Send failed, status=%d\n", wc.status);
        return -1;
    } else {
        printf("[Event-Driven] No completion event received\n");
        return -1;
    }
}

// ------------------- Hybrid Mode -------------------
int wait_hybrid(struct ibv_cq *cq, char *buf, size_t buf_size, struct ibv_comp_channel *channel) {
    struct ibv_wc wc;
    int ne = 0;
    // Phase 1: Limited polling
    for (int i = 0; i < MAX_POLLS; i++) {
        ne = ibv_poll_cq(cq, 1, &wc);
        if (ne > 0) break;
#if POLL_SLEEP_US > 0
        usleep(POLL_SLEEP_US);
#endif
    }
    if (ne > 0) {
        if (wc.status == IBV_WC_SUCCESS) {
            printf("[Hybrid-Poll] Data sent successfully\n");
            return 0;
        } else {
            printf("[Hybrid-Poll] Send failed, status=%d\n", wc.status);
            return -1;
        }
    }
    // Phase 2: Switch to event-driven
    printf("[Hybrid] Polling timed out, switching to event-driven...\n");
    ibv_req_notify_cq(cq, 0);
    ne = ibv_poll_cq(cq, 1, &wc);
    if (ne == 0) {
        struct ibv_cq *ev_cq;
        void *ev_ctx;
        if (ibv_get_cq_event(channel, &ev_cq, &ev_ctx)) {
            perror("ibv_get_cq_event");
            return -1;
        }
        ibv_ack_cq_events(cq, 1);
        ne = ibv_poll_cq(cq, 1, &wc);
    }
    if (ne > 0 && wc.status == IBV_WC_SUCCESS) {
        printf("[Hybrid-Event] Data sent successfully\n");
        return 0;
    } else if (ne > 0) {
        printf("[Hybrid-Event] Send failed, status=%d\n", wc.status);
        return -1;
    } else {
        printf("[Hybrid-Event] No completion event received\n");
        return -1;
    }
}

// ------------------- Main Function -------------------
int main(int argc, char **argv) {
    int opt, mode = MODE_HYBRID;   // Default to hybrid mode
    static struct option long_opts[] = {
        {"mode", required_argument, 0, 'm'},
        {0, 0, 0, 0}
    };
    while ((opt = getopt_long(argc, argv, "m:", long_opts, NULL)) != -1) {
        switch (opt) {
            case 'm':
                if (strcmp(optarg, "poll") == 0) mode = MODE_POLL;
                else if (strcmp(optarg, "event") == 0) mode = MODE_EVENT;
                else if (strcmp(optarg, "hybrid") == 0) mode = MODE_HYBRID;
                else usage(argv[0]);
                break;
            default: usage(argv[0]);
        }
    }
    if (optind >= argc) usage(argv[0]);
    char *server_ip = argv[optind];

    // ========== RDMA Resource Creation ==========
    // 1. Create CM ID
    struct rdma_cm_id *id = NULL;
    int ret;
    ret = rdma_create_id(NULL, &id, NULL, RDMA_PS_TCP);
    if (ret) { perror("rdma_create_id"); return 1; }

    // 2. Convert server IP to sockaddr_in
    struct sockaddr_in server_addr;
    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(7474);
    inet_pton(AF_INET, server_ip, &server_addr.sin_addr);

    // 3. Resolve address
    ret = rdma_resolve_addr(id, NULL, (struct sockaddr *)&server_addr, 2000);
    if (ret) { perror("rdma_resolve_addr"); return 1; }

    // 4. Resolve route
    ret = rdma_resolve_route(id, 2000);
    if (ret) { perror("rdma_resolve_route"); return 1; }

    // 5. Create completion channel (needed for event and hybrid modes)
    struct ibv_comp_channel *channel = ibv_create_comp_channel(id->verbs);
    if (!channel) { perror("ibv_create_comp_channel"); return 1; }

    // 6. Allocate Protection Domain (PD)
    struct ibv_pd *pd = ibv_alloc_pd(id->verbs);
    if (!pd) { perror("ibv_alloc_pd"); return 1; }

    // 7. Create Completion Queue (CQ) (bind channel based on mode)
    struct ibv_cq *cq;
    if (mode == MODE_EVENT || mode == MODE_HYBRID) {
        cq = ibv_create_cq(id->verbs, 10, NULL, channel, 0);
    } else {
        cq = ibv_create_cq(id->verbs, 10, NULL, NULL, 0);
    }
    if (!cq) { perror("ibv_create_cq"); return 1; }

    // 8. Configure QP attributes
    struct ibv_qp_init_attr qp_attr;
    memset(&qp_attr, 0, sizeof(qp_attr));
    qp_attr.cap.max_send_wr = 1;
    qp_attr.cap.max_recv_wr = 1;
    qp_attr.cap.max_send_sge = 1;
    qp_attr.cap.max_recv_sge = 1;
    qp_attr.qp_type = IBV_QPT_RC;
    qp_attr.send_cq = cq;
    qp_attr.recv_cq = cq;

    // 9. Create QP
    ret = rdma_create_qp(id, pd, &qp_attr);
    if (ret) { perror("rdma_create_qp"); return 1; }

    // 10. Register Memory Region (MR)
    char buf[64] = "Hello RDMA";
    struct ibv_mr *mr = ibv_reg_mr(pd, buf, sizeof(buf), IBV_ACCESS_LOCAL_WRITE);
    if (!mr) { perror("ibv_reg_mr"); return 1; }

    // 11. Establish connection
    ret = rdma_connect(id, NULL);
    if (ret) { perror("rdma_connect"); return 1; }
    printf("Connection established, sending data...\n");

    // 12. Post send request
    struct ibv_sge sge = {.addr = (uintptr_t)buf, .length = strlen(buf)+1, .lkey = mr->lkey};
    struct ibv_send_wr send_wr = {.wr_id = 0, .sg_list = &sge, .num_sge = 1, .opcode = IBV_WR_SEND, .send_flags = IBV_SEND_SIGNALED};
    struct ibv_send_wr *bad_send_wr;
    struct timespec t_start, t_end;
    clock_gettime(CLOCK_MONOTONIC, &t_start);
    ret = ibv_post_send(id->qp, &send_wr, &bad_send_wr);
    if (ret) { perror("ibv_post_send"); return 1; }

    // ========== Invoke mode-specific wait function ==========
    int wait_result = -1;
    switch (mode) {
        case MODE_POLL:
            wait_result = wait_polling(cq, buf, sizeof(buf));
            break;
        case MODE_EVENT:
            wait_result = wait_event(cq, buf, sizeof(buf), channel);
            break;
        case MODE_HYBRID:
            wait_result = wait_hybrid(cq, buf, sizeof(buf), channel);
            break;
    }
    clock_gettime(CLOCK_MONOTONIC, &t_end);
    if (wait_result == 0) {
        long latency_ns = (t_end.tv_sec - t_start.tv_sec) * 1000000000L + (t_end.tv_nsec - t_start.tv_nsec);
        printf("(latency: %ld us)\n", (latency_ns + 500) / 1000);
    }
    return wait_result;
}
