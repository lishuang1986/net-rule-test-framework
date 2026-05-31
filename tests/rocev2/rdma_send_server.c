#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <getopt.h>
#include <arpa/inet.h>
#include <rdma/rdma_cma.h>

#define MAX_POLLS   10000
#define POLL_SLEEP_US 0

enum mode { MODE_POLL, MODE_EVENT, MODE_HYBRID };

void usage(const char *prog) {
    fprintf(stderr, "Usage: %s --mode <poll|event|hybrid>\n", prog);
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
        printf("[Polling Mode] Received data: %s\n", buf);
        return 0;
    } else {
        printf("[Polling Mode] Receive failed, status=%d\n", wc.status);
        return -1;
    }
}

// ------------------- Event-Driven Mode -------------------
// channel is the last parameter (kept for uniform signature, though unused in polling mode)
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
        printf("[Event-Driven] Received data: %s\n", buf);
        return 0;
    } else if (ne > 0) {
        printf("[Event-Driven] Receive failed, status=%d\n", wc.status);
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
            printf("[Hybrid-Poll] Received data: %s\n", buf);
            return 0;
        } else {
            printf("[Hybrid-Poll] Receive failed, status=%d\n", wc.status);
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
        printf("[Hybrid-Event] Received data: %s\n", buf);
        return 0;
    } else if (ne > 0) {
        printf("[Hybrid-Event] Receive failed, status=%d\n", wc.status);
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
        {
            .name = "mode",
            .has_arg = required_argument,
            .flag = NULL,
            .val = 'm',
        },
        {0},
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

    // ========== RDMA Resource Creation ==========
    // 1. Create listening CM ID
    struct rdma_cm_id *listen_id = NULL, *conn_id = NULL;
    int ret = rdma_create_id(NULL, &listen_id, NULL, RDMA_PS_TCP);
    if (ret) { perror("rdma_create_id"); return 1; }

    // 2. Bind address and port
    struct sockaddr_in server_addr = {
        .sin_family = AF_INET,
        .sin_addr.s_addr = INADDR_ANY,
        .sin_port = htons(7474),
    };
    ret = rdma_bind_addr(listen_id, (struct sockaddr *)&server_addr);
    if (ret) { perror("rdma_bind_addr"); return 1; }

    // 3. Listen
    ret = rdma_listen(listen_id, 1);
    if (ret) { perror("rdma_listen"); return 1; }
    printf("Waiting for connection...\n");

    // 4. Accept connection
    ret = rdma_get_request(listen_id, &conn_id);
    if (ret) { perror("rdma_get_request"); return 1; }
    printf("Client connected\n");

    // 5. Create completion channel (needed for event and hybrid modes)
    struct ibv_comp_channel *channel = ibv_create_comp_channel(conn_id->verbs);
    if (!channel) { perror("ibv_create_comp_channel"); return 1; }

    // 6. Allocate Protection Domain (PD)
    struct ibv_pd *pd = ibv_alloc_pd(conn_id->verbs);
    if (!pd) { perror("ibv_alloc_pd"); return 1; }

    // 7. Create Completion Queue (CQ)  (bind channel based on mode)
    struct ibv_cq *cq;
    if (mode == MODE_EVENT || mode == MODE_HYBRID) {
        cq = ibv_create_cq(conn_id->verbs, 10, NULL, channel, 0);
    } else {
        cq = ibv_create_cq(conn_id->verbs, 10, NULL, NULL, 0);
    }
    if (!cq) { perror("ibv_create_cq"); return 1; }

    // 8. Configure QP attributes
    struct ibv_qp_init_attr qp_attr = {
        .cap = {
            .max_send_wr = 1,
            .max_recv_wr = 1,
            .max_send_sge = 1,
            .max_recv_sge = 1,
        },
        .qp_type = IBV_QPT_RC,
        .send_cq = cq,
        .recv_cq = cq,
    };

    // 9. Create QP
    ret = rdma_create_qp(conn_id, pd, &qp_attr);
    if (ret) { perror("rdma_create_qp"); return 1; }

    // 10. Register Memory Region (MR)
    char buf[64] = {0};
    struct ibv_mr *mr = ibv_reg_mr(pd, buf, sizeof(buf),
                                   IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE);
    if (!mr) { perror("ibv_reg_mr"); return 1; }

    // 11. Post receive request (Recv WQE)
    struct ibv_sge sge = {
        .addr = (uintptr_t)buf,
        .length = sizeof(buf),
        .lkey = mr->lkey,
    };
    struct ibv_recv_wr recv_wr = {
        .wr_id = 0,
        .sg_list = &sge,
        .num_sge = 1,
    };
    struct ibv_recv_wr *bad_recv_wr;
    ret = ibv_post_recv(conn_id->qp, &recv_wr, &bad_recv_wr);
    if (ret) { perror("ibv_post_recv"); return 1; }

    // 12. Accept connection (transition QP to RTR/RTS)
    ret = rdma_accept(conn_id, NULL);
    if (ret) { perror("rdma_accept"); return 1; }
    printf("Connection established, waiting for data...\n");

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
    return wait_result;
}
